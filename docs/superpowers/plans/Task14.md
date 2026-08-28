# Task 14 Final Review, Documentation, and Offline Release Audit Plan

> **For Codex:** REQUIRED SUB-SKILL: Use `superpowers:executing-plans` when this plan is approved. Use `superpowers:systematic-debugging` and `superpowers:test-driven-development` for every approved code defect. Use `superpowers:verification-before-completion` before reporting review results. Do not use subagents, branches, worktrees, staging, commits, pushes, pulls, fetches, or any remote mutation.

**Goal:** Perform an evidence-based final review of every Task 1–13 module, fix only defects explicitly approved by the user, publish concise and accurate local usage/API documentation, and prove the package, safety boundary, and offline test suite from a clean environment.

**Architecture:** Task 14 is split by a hard human gate. Phase A is read-only and produces a complete findings list with reproducible evidence. No production fix or public documentation is written until the user approves the findings and exact fix set. Phase B applies only approved fixes through RED → minimal GREEN → regression. Phase C creates documentation behind executable document-contract tests. Phase D performs fresh offline installation, Windows-specific safety tests, privacy audits, source audits, and full regression. Task 14 never plans, creates, edits, or validates video, ZIP, release, upload, or repository-visibility artifacts.

**Tech stack:** Python 3.11+, standard library, official `openai` package already declared by the repository, pytest, PowerShell on Windows, Git read-only commands, and built-in AST/source inspection. No new dependency is authorized.

**Binding sources:** `AGENTS.md`, `DESIGN.md`, `TASKS.md`, the accepted Task 8–13 plans, all current source/tests, and `requirement.pdf`. Current official API facts must be checked against the [Responses create reference](https://developers.openai.com/api/reference/cli/resources/responses/methods/create) and [function-calling guide](https://developers.openai.com/api/docs/guides/function-calling); repository behavior remains defined by the accepted local implementation and tests.

---

## 1. Scope and explicit exclusions

Task 14 includes only:

1. A systematic final review of all Task 1–13 production code, tests, packaging, demo fixture, and approved design contracts.
2. Fixes for evidence-backed findings that the user explicitly approves.
3. A concise `README.txt`, a navigational `README.md`, a detailed `docs/USAGE.md`, and a detailed `docs/OPENAI_API.md`.
4. Automated documentation-contract tests.
5. Fully offline regression, clean-wheel installation, Windows safety/process tests, credential/privacy scans, dependency/framework scans, and Git diff/status review.

Task 14 excludes:

- video planning, scripts, recording, editing, compression, format checking, duration checking, or acceptance;
- ZIP creation or inspection;
- GitHub visibility/settings, releases, uploads, submission packaging, and remote operations;
- real OpenAI API calls in automated or final verification;
- new providers, custom `base_url`, Azure OpenAI, proxy support, streaming, async APIs, server conversations, and Task 15 work;
- opportunistic refactors, style-only rewrites, dependency upgrades, or improvements without a confirmed defect.

Task 14 remains `进行中` when execution stops for final user review.

---

## 2. Locked file map

### 2.1 Read-only review set

The following are reviewed in full and remain read-only unless an exact finding ID is later approved:

- `AGENTS.md`
- `DESIGN.md`
- `requirement.pdf`
- `pyproject.toml`
- `.gitignore`
- every file under `docs/superpowers/plans/`, especially `Task8.md` through `Task13.md`
- every `src/coding_agent/**/*.py` file
- every `tests/**/*.py` file
- every file under `examples/broken_pytest_project/`
- Git history, local branch metadata, tracked-file list, and the configured origin URL through read-only Git commands

The initial conditional production-code modification set is **empty**. A production file enters that set only when all of these are true:

1. a finding identifies its exact path and line;
2. a deterministic reproduction demonstrates the violated invariant;
3. the finding is `Critical` or `Important`, or the user separately approves a `Minor` item;
4. the user approves the proposed test and fix;
5. the fix does not require a new dependency, public-interface redesign, or a change outside Task 14.

If an approved fix later requires a file not named in its approved finding, stop and request a scope amendment before editing it.

### 2.2 Unconditionally permitted after the findings gate

- Modify `TASKS.md` only to:
  - change Task 13 from `进行中` to `已完成`;
  - replace Task 14's obsolete video/ZIP wording with this approved code-review/documentation/offline-audit scope;
  - change Task 14 from `未开始` to `进行中`;
  - leave all other task statuses unchanged and keep exactly one `进行中` task.
- Create `README.txt`.
- Modify `README.md` from its placeholder into a short landing page that links to the three public documents without duplicating their detailed content.
- Create `docs/USAGE.md`.
- Create `docs/OPENAI_API.md`.
- Create `tests/test_docs.py`.
- Retain this approved `docs/superpowers/plans/Task14.md`.

`DESIGN.md`, `AGENTS.md`, earlier plans, and `requirement.pdf` are not rewritten merely to restate Task 14. Any real inconsistency in them must be reported as a finding and separately approved.

### 2.3 Never modified in Task 14

- dependency declarations unless a confirmed, user-approved defect makes the current package un-installable; a new dependency remains prohibited;
- the demo's tracked defects or tests merely to make the example pass in place;
- Git configuration, remotes, branches, tags, or history;
- `.coding-agent/` runtime logs as documentation source material;
- any file outside the repository.

---

## 3. Review approach and findings contract

### 3.1 Approaches considered

1. **Evidence-gated staged review — selected.** Review the whole repository read-only, publish reproducible findings, wait for approval, then apply only approved fixes before writing docs. This prevents documentation from blessing defective behavior and prevents review from turning into uncontrolled refactoring.
2. **Documentation first.** Faster to produce files, but it risks documenting behavior that the final review later changes.
3. **Review and fix opportunistically.** Shorter feedback loop, but violates the explicit approval gate and makes the final diff difficult to defend.

### 3.2 Severity definitions

- **Critical:** credential/privacy disclosure; workspace escape; protected-path or command-policy bypass; required-verification bypass producing false success; destructive/remote/unbounded execution; or a path that can return exit `0` without fresh passing evidence.
- **Important:** deterministic functional failure of an accepted requirement; off-by-one or missing budget enforcement; illegal message/continuation history; incorrect exit/report/log facts; broken install/CLI entry; or missing tests around an accepted invariant where a concrete failure is reproducible.
- **Minor:** maintainability, naming, redundancy, localized clarity, or documentation polish that does not currently violate correctness, security, privacy, or an accepted public contract.

Severity is based on demonstrated impact, not code aesthetics. No count target exists; an empty category is valid.

### 3.3 Required finding template

Every finding uses this exact structure:

```text
ID: F-001
Severity: Critical | Important | Minor
Location: repository/relative/path.py:<exact line>
Violated requirement/invariant: <one accepted rule and its source>
Evidence command: <one exact offline/read-only command>
Observed result: <actual exit code and minimal output>
Expected result: <deterministic expected behavior>
Impact: <specific reachable consequence>
Proposed fix: <smallest scoped change>
Test change: <exact test file and new/changed test behavior>
Allowed files if approved: <complete list>
```

Evidence must be reproducible from the clean checkout. A suspicion, theoretical race outside the documented threat model, unsupported platform claim, or stylistic preference is not a defect. Accepted first-version limitations are recorded separately and are not findings.

### 3.4 Human approval gate

After the six review batches below:

1. publish the complete ordered findings list, including an explicit `No finding` result for clean batches;
2. list accepted limitations separately;
3. list planning/documentation gaps separately from code defects;
4. stop without editing source, tests, public docs, or task statuses;
5. wait for the user to approve exact finding IDs and their proposed file/test set.

`Critical` and `Important` findings cannot be fixed before that approval. `Minor` findings are recorded only and remain unchanged unless individually approved.

---

## 4. README and documentation contracts

### 4.1 `README.txt` size semantics

The PDF requires an exact file named `README.txt`, no more than “1000 汉字”, containing the Git repository URL, run method, feature description, and optional notes. The PDF does not define a counting algorithm. Task 14 therefore adopts a stricter deterministic gate:

- normalize CRLF and CR to LF for character metrics and ignore only final LF characters;
- hard limit: **850 total Unicode code points**;
- authoring target: **650–800 total Unicode code points**;
- also require Chinese Han count `<= 1000`;
- always report total Unicode code points, non-whitespace code points, Han characters in `U+4E00–U+9FFF`, raw UTF-8 bytes, and logical line count;
- decode as strict UTF-8 and omit a UTF-8 BOM.

The 850-code-point hard limit is intentionally more conservative than the ambiguous 1000-Han-character requirement and leaves at least 15% margin.

`README.txt` must contain:

- the project purpose and provider-neutral local architecture in plain language;
- repository URL `https://github.com/zt150058/MiniCodex`;
- Windows-first and Python 3.11+ requirements;
- minimal virtual-environment/install/config/run commands;
- `--workspace`, optional `--verify`, and the recommended demo verification `pytest -q`;
- `.coding-agent/logs/` location;
- the fresh-verification condition for success;
- the non-OS-sandbox warning;
- paths to `docs/USAGE.md` and `docs/OPENAI_API.md`;
- no video, ZIP, deadline, personal path, real-looking key, or unsupported capability claim.

### 4.2 `README.md`

`README.md` is a short repository landing page, not the assessment-limited file. It contains:

- project summary;
- links to `README.txt`, `docs/USAGE.md`, and `docs/OPENAI_API.md`;
- a one-command pointer to `coding-agent --help`;
- an explicit statement that the repository is Windows-first, executes only a bounded command set, and is not an OS sandbox.

It does not duplicate the full usage or API guide.

### 4.3 `docs/USAGE.md` outline

Use these exact top-level sections:

1. `# MiniCodex 使用说明`
2. `## 功能与适用场景`
3. `## 已验证环境与系统要求`
4. `## Windows PowerShell 安装`
5. `## 工作区与凭据准备`
6. `## CLI 参数`
7. `## 最小运行示例`
8. `## 推荐的安全运行示例`
9. `## Agent 运行流程`
10. `## 五个本地工具`
11. `## 成功、验证与退出码`
12. `## JSONL 日志与 FinalReport`
13. `## 离线演示与完整测试`
14. `## 常见错误与排查`
15. `## 停止运行与清理`
16. `## 安全边界和已知限制`

The guide must state only verified facts:

- Python `>=3.11`, Windows-first; no claim of supported Linux/macOS behavior;
- create `.venv`, install the project, and confirm `coding-agent --help`;
- set `OPENAI_API_KEY` and either `OPENAI_MODEL` or `--model`;
- parser shape: positional `task`; required `--workspace`; optional `--verify`; optional `--model`; `-h/--help`;
- `--verify "pytest -q"` is startup-authorized and is a required final gate when supplied;
- tool names exactly `list_directory`, `read_file`, `replace_text`, `write_file`, `run_command`;
- `SUCCESS` requires fresh passing evidence and `validation_index == mutation_index`;
- exits `0`, `1`, `2`, and `130` with their exact meanings;
- JSONL path `.coding-agent/logs/<run_id>.jsonl` and the bounded final JSON report;
- stopping with `Ctrl+C`, then checking the nonzero/interrupted result;
- removing `.coding-agent` is a user-initiated cleanup after the process stops; the Agent itself has no delete tool;
- the offline demo is the deterministic integration test, not a fake CLI flag:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\integration\test_agent_repair.py -q -p no:cacheprovider
```

- the full offline suite is:

```powershell
.\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider
```

- workspace code and tests are treated as trusted; allowed subprocesses may access operating-system resources, so the policy is not an OS sandbox;
- use a copied/disposable, backed-up workspace for experiments.

### 4.4 `docs/OPENAI_API.md` outline

Use these exact top-level sections:

1. `# OpenAI Responses API 接入说明`
2. `## 凭据与模型配置`
3. `## PowerShell 当前会话设置`
4. `## 不显示密钥的配置检查`
5. `## 启动 MiniCodex`
6. `## ModelClient 与适配器边界`
7. `## Responses API 请求映射`
8. `## 工具调用和 call_id 配对`
9. `## 本地历史与 continuation`
10. `## logical call 与 provider attempt`
11. `## 重试和永久错误`
12. `## 隐私与日志边界`
13. `## 完全离线的自动测试`
14. `## 手工联网冒烟（自动测试不会执行）`
15. `## 常见 API 错误`
16. `## 当前未实现的扩展`

Required content and examples:

- Require an official OpenAI API key and use placeholder `$env:OPENAI_API_KEY = '<your-api-key>'`; never include a key-shaped value.
- Set only the current PowerShell session by default:

```powershell
$env:OPENAI_API_KEY = '<your-api-key>'
$env:OPENAI_MODEL = '<model-id-available-to-your-account>'
```

- Check presence without printing the value:

```powershell
if ([string]::IsNullOrWhiteSpace($env:OPENAI_API_KEY)) { 'missing' } else { 'configured' }
if ([string]::IsNullOrWhiteSpace($env:OPENAI_MODEL)) { 'missing' } else { 'configured' }
```

- Explain that persistent user/system environment variables have a larger exposure window; do not teach storing the key in source, docs, CLI arguments, Git, screenshots, or videos.
- Do not hard-code a recommended model. State that model names, permissions, pricing, and availability can change and should be confirmed in official OpenAI documentation/account settings.
- Explain that `OpenAIResponsesClient` is the only SDK boundary and returns the existing internal `ModelResponse`.
- State that production calls `client.responses.create`, explicitly sends `store=False`, uses strict function tools, maps `function_call_output` by `call_id`, and does not use Chat Completions.
- Explain that local history is authoritative; no server `conversation` or `previous_response_id` replaces it.
- Explain that continuation snapshots and encrypted reasoning remain opaque, repr-hidden, in-memory only, are replayed only for the matching local assistant message, and are cleared after context compression.
- Explain the adapter's deterministic retry schedule: initial attempt plus at most two retries, delays `0.25` and `0.50` seconds, no jitter; transient classes are 429, 5xx, timeout, and temporary connection failure; authentication, permission, not-found/model, bad request, unprocessable request, parsing, and local mapping failures do not retry.
- State that official SDK retries are disabled with `max_retries=0`.
- Distinguish a logical Agent model call from each physical provider attempt and explain the shared run budget.
- State that keys, Authorization values, provider exception bodies, request bodies, continuation payloads, and hidden reasoning do not enter the normal log/report schemas.
- Mark the real smoke example as manual, networked, billable, nondeterministic, and requiring explicit user authorization. It must use a disposable copy of the demo and must not be part of pytest.
- The `当前未实现的扩展` table must mark all of these as `当前未实现`: custom `base_url`, Azure OpenAI, third-party compatible endpoints, proxy configuration, server conversation, streaming, async API, other provider adapters.
- Explain that a future provider implements `ModelClient` and returns internal `ModelResponse`; it does not modify `AgentRunner` or leak SDK types.

---

## 5. Documentation contract test design

Create `tests/test_docs.py` before public documentation. It uses only the standard library and pytest. Its public test inventory is locked:

```python
def test_required_public_documents_exist_and_are_utf8() -> None: ...
def test_readme_txt_meets_submission_contract() -> None: ...
def test_all_markdown_relative_links_and_source_references_exist() -> None: ...
def test_usage_matches_parser_tools_exit_codes_and_log_path() -> None: ...
def test_openai_guide_matches_adapter_and_declares_unsupported_features() -> None: ...
def test_public_docs_contain_no_secret_or_personal_absolute_path() -> None: ...
```

Locked helpers and semantics:

```python
from __future__ import annotations

from dataclasses import dataclass
import re
from pathlib import Path

from coding_agent.cli import build_parser
from coding_agent.report import FinalReport
from coding_agent.tools.filesystem import (
    ListDirectoryTool,
    ReadFileTool,
    ReplaceTextTool,
    WriteFileTool,
)
from coding_agent.tools.shell import RunCommandTool

ROOT = Path(__file__).resolve().parents[1]
PUBLIC_DOCS = (
    ROOT / "README.md",
    ROOT / "README.txt",
    ROOT / "docs" / "USAGE.md",
    ROOT / "docs" / "OPENAI_API.md",
)
README_HARD_TOTAL = 850


@dataclass(frozen=True, slots=True)
class ReadmeMetrics:
    unicode_chars: int
    non_whitespace_chars: int
    han_chars: int
    utf8_bytes: int
    lines: int


def _read_utf8(path: Path) -> str:
    raw = path.read_bytes()
    assert not raw.startswith(b"\xef\xbb\xbf")
    return raw.decode("utf-8")


def _readme_metrics(path: Path) -> ReadmeMetrics:
    raw = path.read_bytes()
    text = raw.decode("utf-8")
    normalized = text.replace("\r\n", "\n").replace("\r", "\n").rstrip("\n")
    return ReadmeMetrics(
        unicode_chars=len(normalized),
        non_whitespace_chars=sum(not char.isspace() for char in normalized),
        han_chars=sum("\u4e00" <= char <= "\u9fff" for char in normalized),
        utf8_bytes=len(raw),
        lines=0 if not normalized else len(normalized.splitlines()),
    )
```

Each test must assert these concrete contracts:

- all four files exist and strict UTF-8 decoding succeeds;
- `README.txt` total Unicode count is `<= 850`, Han count is `<= 1000`, contains the exact public repository URL, contains run/feature/workspace/verify/log/safety information, and links by literal path to both detailed guides;
- every relative Markdown link in `README.md`, `docs/USAGE.md`, and `docs/OPENAI_API.md` resolves to an existing repository path; HTTP(S) links are excluded from local existence checks;
- every backticked `src/...`, `tests/...`, or `examples/...` reference resolves to an existing path;
- `build_parser().format_help()` contains exactly the documented positional/option names;
- documented tool names equal the five class `name` attributes in fixed composition order;
- documentation contains exit codes `0`, `1`, `2`, `130`; report status names; `.coding-agent/logs/<run_id>.jsonl`; `OPENAI_API_KEY`; and `OPENAI_MODEL`;
- source audit finds `responses.create`, `store=False`, `max_retries=0`, and the strict schema path in `openai_client.py`, and finds no Chat Completions call;
- API guide explicitly marks every forbidden extension as currently unimplemented;
- no public document matches `sk-` followed by 16 or more credential characters, `Bearer` followed by a token, a Windows personal path such as a drive plus `Users`, or a repository-author absolute path;
- the networked smoke section carries the exact manual-only heading and no pytest test calls it.

Tests assert public behavior and source-level boundary facts only. They do not execute documentation commands, read environment secret values, import the OpenAI SDK outside its accepted adapter, or contact a network.

---

## 6. Execution tasks

### Task 0: Reconfirm the Task 13 baseline — read only

**Files:** Read every path in the review set; modify nothing.

**Step 1 — repository identity and local push evidence**

Run:

```powershell
$repo = git rev-parse --show-toplevel
Set-Location $repo
git branch --show-current
git rev-parse HEAD
git rev-parse '@{upstream}'
git log -5 --oneline
git status --branch --short
git status --short --untracked-files=all
git diff --check
git remote get-url origin
```

Expected: repository root is the intended MiniCodex checkout; branch is `main`; HEAD is the accepted Task 13 commit; local upstream tracking reference equals HEAD; status is empty except the approved Task14 plan if not committed; `git diff --check` exits `0`; origin is the documented repository URL. Because `fetch` is prohibited, report this precisely as “HEAD equals the local `origin/main` tracking reference,” not as proof of current remote server state.

**Step 2 — complete baseline reading**

Read `AGENTS.md`, `DESIGN.md`, `TASKS.md`, Task8–Task13 plans, every production/test/example file, packaging/ignore/readme files, and both PDF pages. Record the current file list with:

```powershell
rg --files src tests examples docs | Sort-Object
git ls-files README* AGENTS.md DESIGN.md TASKS.md pyproject.toml .gitignore requirement.pdf
```

Expected: no file is silently omitted. Confirm from the PDF rather than memory that the assessment file is `README.txt` and its stated limit is 1000 Han characters.

**Step 3 — fresh full baseline**

```powershell
$baselineTemp = Join-Path ([System.IO.Path]::GetTempPath()) ("coding-agent-task14-baseline-" + [guid]::NewGuid())
$env:PYTHONDONTWRITEBYTECODE = '1'
.\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider --basetemp $baselineTemp
```

Expected: exit `0`; report actual pass/fail/skip/warning counts. Any failure stops Task 14 before findings review.

**Acceptance:** Clean, accepted Task13 baseline; all sources read; PDF readable; no edit or status change.

---

### Task 1: Complete read-only code review and findings gate

**Files:** Entire read-only review set. No writes.

Review each batch in order. For every batch, inspect source and corresponding tests, run the listed focused tests, and complete either one or more finding records or an explicit no-finding record.

#### Batch A — architecture, provider boundary, package graph

Review `messages.py`, `model.py`, `openai_client.py`, `app.py`, `cli.py`, `config.py`, `pyproject.toml`, and import edges.

Verify: local Agent ownership; no Agent SDK/framework; provider-neutral types; SDK import isolation; Responses-only mapping; `store=False`; local history; strict tools; retry classes/count/delays; SDK retries disabled; no unit-test network path; startup validation before provider construction; no duplicate execution policy.

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_messages.py tests\test_model.py tests\test_openai_client.py tests\test_app.py tests\test_cli.py -q -p no:cacheprovider
rg -n "^(from|import) (openai|langchain|llama_index|autogen|crewai)" src tests pyproject.toml
rg -n "responses\.create|store=False|max_retries=0|chat\.completions|previous_response_id|conversation" src\coding_agent
```

#### Batch B — messages, continuation, context, and summary lifecycle

Review `messages.py`, `model.py`, `openai_client.py`, `context.py`, relevant state fields, and context/adapter tests.

Verify: legal message order; unique paired `call_id`; multi-tool order; no orphan result; continuation index integrity; no duplicate replay; continuation cleared atomically after compression; summary continuation discarded; deterministic fallback; no serialization/repr/log/report path for continuation or encrypted reasoning.

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_messages.py tests\test_openai_client.py tests\test_context.py -q -p no:cacheprovider
.\.venv\Scripts\python.exe -m pytest tests\test_agent_loop.py -k "continuation or compression or summary" -q -p no:cacheprovider
```

#### Batch C — Agent state machine, budgets, repetition, and verification

Review `state.py`, `agent.py`, `termination.py`, `verification.py`, `model.py`, and corresponding tests.

Verify: legal transitions; no success without fresh passing verification; no operation after terminal state; stable simultaneous-reason priority; logical/provider/tool/verification/mutation/validation/runtime counters; exact-limit semantics; summary and retry shared budget; blocked operation not counted; repeat/error reset rules; required capability cannot be replaced; time/tool budget gates; interruption and `SystemExit` semantics.

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_termination.py tests\test_verification.py tests\test_agent_loop.py -q -p no:cacheprovider
.\.venv\Scripts\python.exe -m pytest tests\test_agent_loop.py -k "limit or budget or verification or interrupt or system_exit or repeated" -q -p no:cacheprovider
```

#### Batch D — filesystem, command, workspace, and Windows process safety

Review `safety.py`, `tools/base.py`, `tools/registry.py`, `tools/filesystem.py`, `tools/shell.py`, `config.py`, and all tool/safety tests.

Verify: relative containment; drive/UNC/device/ADS/reserved/trailing-dot forms; protected components; every reparse form; guarded new parent; bounded reads/writes; exact replace/create-only behavior; allowlist and Git read-only rules; control syntax; trusted executable resolution; environment removal; `shell=False`; fixed cwd; per-stream limits; timeout; child-tree cleanup; startup/cleanup error facts; required verification uses the same authorized capability. Record the accepted TOCTOU/OS-sandbox limitation separately, not as a defect.

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_path_safety.py tests\test_command_safety.py tests\tools\test_read_tools.py tests\tools\test_write_tools.py tests\tools\test_shell_tool.py -q -p no:cacheprovider
.\.venv\Scripts\python.exe -m pytest tests\test_path_safety.py -k "symlink or junction or reparse or dangling or protected or outside" -q -p no:cacheprovider
.\.venv\Scripts\python.exe -m pytest tests\tools\test_shell_tool.py -k "process_tree or cleanup or timeout or truncat or shell_false or environment" -q -p no:cacheprovider
```

No permanent skip/xfail may substitute for a Windows reparse or process-tree behavior on the target platform.

#### Batch E — event log, final report, CLI, and composition lifecycle

Review `logging.py`, `report.py`, `app.py`, `cli.py`, `agent.py`, and related tests.

Verify: continuous sequence; unique first/last events; before/after order; no false completion for blocked operations; logger failure blocks later operations; close failure cannot preserve success; report uses only state/metadata; report/exit agreement; exactly one report; allowlisted privacy data; shared workspace/executor/capability/clock/logger; fixed tool order; stdout/stderr boundaries; startup and interruption exits; no accidental production network during construction.

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_logging.py tests\test_report.py tests\test_app.py tests\test_cli.py -q -p no:cacheprovider
.\.venv\Scripts\python.exe -m pytest tests\test_agent_loop.py -k "event or log or terminal or verification" -q -p no:cacheprovider
```

#### Batch F — integration, packaging, docs, dead code, and test quality

Review every test, the demo fixture, `pyproject.toml`, `.gitignore`, current README/docs, public signatures, exceptions, resource cleanup, imports, long/multi-purpose functions, and whether tests assert real public behavior rather than only mock calls.

```powershell
.\.venv\Scripts\python.exe -m pytest tests\integration tests\test_app.py tests\test_cli.py -q -p no:cacheprovider
.\.venv\Scripts\python.exe -m pip check
rg -n "pytest\.skip|pytest\.xfail|@pytest\.mark\.(skip|xfail)" tests
rg -n "TO[D]O|TB[D]|NotImplementedError|pass\s*(#.*)?$" src tests docs
```

Manually distinguish deliberate test helper bodies from unfinished production code. Confirm the tracked demo remains broken and every integration test copies it before mutation.

**Checkpoint:** Publish the full findings list and stop. Do not update `TASKS.md`, write public documentation, or fix anything until the user approves exact IDs.

---

### Task 2: Activate the approved Task 14 scope after findings approval

**Files:** Modify only `TASKS.md`.

After the user approves the findings disposition, update the three locked Task 13/14 status/scope items from section 2.2. Then run:

```powershell
Select-String -Path TASKS.md -Pattern '当前状态|进行中|已完成|未开始'
git diff -- TASKS.md
```

Expected: Task 13 is `已完成`; Task 14 is the only `进行中` task; video/ZIP requirements are absent from Task 14; no earlier task text/status changes.

**Acceptance:** Bookkeeping matches the user-approved scope without changing code.

---

### Task 3: Apply only user-approved findings through strict TDD

**Files:** Initially none. For each approved finding, only the exact `Allowed files if approved` list in that finding.

For each approved ID independently:

1. invoke `superpowers:systematic-debugging` and reproduce the finding with its evidence command;
2. write the smallest test in the approved test path that demonstrates the violated public invariant;
3. run only that test and confirm a nonzero RED for the expected behavioral reason, not syntax/import/fixture failure;
4. make the smallest production or documentation correction in the approved file set;
5. rerun the exact test for GREEN;
6. run that module's full focused suite;
7. run the Task 1–13 complete regression before proceeding to the next finding;
8. report commands, exit codes, counts, and changed files;
9. do not combine unrelated findings in one patch.

If a finding cannot be reproduced, already passes, requires a public redesign/new dependency, or needs an unapproved file, stop and return it to the user instead of modifying code. Approved `Minor` work follows the same TDD/evidence path where behavior changes; pure text corrections still require the documentation contract test first.

**Acceptance:** Every code change corresponds one-to-one with an approved finding, has a fresh RED/GREEN trail, and preserves all unrelated interfaces.

---

### Task 4: Write document-contract tests first

**Files:** Create `tests/test_docs.py` only.

Implement the exact inventory and helpers in section 5. Do not create the missing public docs yet.

Run RED tests separately:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_docs.py::test_required_public_documents_exist_and_are_utf8 -q -p no:cacheprovider
.\.venv\Scripts\python.exe -m pytest tests\test_docs.py::test_readme_txt_meets_submission_contract -q -p no:cacheprovider
.\.venv\Scripts\python.exe -m pytest tests\test_docs.py::test_all_markdown_relative_links_and_source_references_exist -q -p no:cacheprovider
.\.venv\Scripts\python.exe -m pytest tests\test_docs.py::test_usage_matches_parser_tools_exit_codes_and_log_path -q -p no:cacheprovider
.\.venv\Scripts\python.exe -m pytest tests\test_docs.py::test_openai_guide_matches_adapter_and_declares_unsupported_features -q -p no:cacheprovider
```

Expected: nonzero because `README.txt`, `docs/USAGE.md`, and `docs/OPENAI_API.md` do not exist and `README.md` is still a placeholder. Any syntax/import error is an invalid RED and must be corrected before writing docs.

Run the existing regression after the test file itself imports successfully:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_cli.py tests\test_app.py tests\test_openai_client.py -q -p no:cacheprovider
```

**Acceptance:** Every public-document requirement has a failing executable contract before documentation is authored.

---

### Task 5: Create `README.txt` and replace the placeholder landing page

**Files:** Create `README.txt`; modify `README.md`.

Write the exact content contract from sections 4.1 and 4.2. Keep `README.txt` between 650 and 800 total normalized Unicode code points and never above 850.

Run GREEN:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_docs.py::test_readme_txt_meets_submission_contract -q -p no:cacheprovider
```

Expected: the `README.txt` contract is GREEN. The combined all-documents existence test is intentionally deferred until both detailed guides are created in Tasks 6 and 7. Run this deterministic metric report:

```powershell
.\.venv\Scripts\python.exe -c "from pathlib import Path; import json; p=Path('README.txt'); b=p.read_bytes(); t=b.decode('utf-8').replace('\r\n','\n').replace('\r','\n').rstrip('\n'); m={'unicode_chars':len(t),'non_whitespace_chars':sum(not c.isspace() for c in t),'han_chars':sum('\u4e00'<=c<='\u9fff' for c in t),'utf8_bytes':len(b),'lines':0 if not t else len(t.splitlines())}; print(json.dumps(m,ensure_ascii=False,sort_keys=True)); assert m['unicode_chars']<=850 and m['han_chars']<=1000"
```

Expected: exit `0`, target 650–800 total characters, all five metrics printed, exact repository URL present.

**Acceptance:** Assessment file is conservatively under the PDF limit; README landing page is no longer a placeholder; detailed links are named but may remain RED until their next steps.

---

### Task 6: Create the first-user usage guide

**Files:** Create `docs/USAGE.md`; adjust `README.md`/`README.txt` only if a link or wording contract is wrong.

Write the exact outline and verified facts from section 4.3. Derive CLI text from `build_parser().format_help()`, exits from `cli.py`/`app.py`/`report.py`, tool names from the fixed registry construction, and log/report fields from Task 12 types. Do not document a CLI fake mode or a direct offline Agent command that does not exist.

Run GREEN:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_docs.py::test_usage_matches_parser_tools_exit_codes_and_log_path -q -p no:cacheprovider
.\.venv\Scripts\coding-agent.exe --help
```

Expected: exit `0`; documented options, positional task, and help output agree. If the read-only review confirmed stale help wording and the user approved that finding, its separate RED/GREEN fix must already have occurred in Task 3; do not silently alter `cli.py` here.

**Acceptance:** A first-time Windows user can install, configure, run, verify, inspect, stop, clean local logs, execute the offline demo, and understand safety limits using only commands that exist.

---

### Task 7: Create the OpenAI Responses API guide

**Files:** Create `docs/OPENAI_API.md`; adjust public-doc links only if needed.

Write the exact outline/content from section 4.4. Cross-check every repository-specific statement against `openai_client.py`, `model.py`, `messages.py`, `context.py`, `logging.py`, and their tests. Cross-check general API field meanings against the official OpenAI sources linked in this plan. Never infer current model availability or recommend an unverified model.

Run GREEN:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_docs.py::test_openai_guide_matches_adapter_and_declares_unsupported_features -q -p no:cacheprovider
.\.venv\Scripts\python.exe -m pytest tests\test_docs.py::test_public_docs_contain_no_secret_or_personal_absolute_path -q -p no:cacheprovider
```

Expected: exit `0`; no key-shaped string or personal absolute path; every unsupported feature is explicitly labeled `当前未实现`; manual smoke is clearly excluded from automation.

**Acceptance:** The API guide accurately explains official Responses integration without leaking SDK types into the core or claiming unsupported providers/features.

---

### Task 8: Finish documentation links and run the complete contract suite

**Files:** Only the four public docs and `tests/test_docs.py` for a confirmed contract-test defect.

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_docs.py -q -p no:cacheprovider
.\.venv\Scripts\coding-agent.exe --help
```

Expected: all six document tests pass; no relative link or source reference is broken; exact parser/tool/env/log/exit/API facts agree.

Then manually review every fenced PowerShell command. Classify it as one of:

- safe local setup/inspection;
- offline pytest;
- normal production API invocation;
- explicitly manual network smoke.

No automatic test may execute the final category.

**Acceptance:** Documentation is internally linked, testable, truthful, and free of personal paths/secrets.

---

### Task 9: Clean offline install and real entry-point checks

**Files:** No repository edits. Temporary files live under the OS temporary directory.

Build a wheel with the accepted environment, install it without dependency resolution into a new venv, and prove the console entry. This validates package/entry-point installation fully offline; it does not pretend to re-download the already-declared `openai` dependency.

```powershell
$auditRoot = Join-Path ([System.IO.Path]::GetTempPath()) ("coding-agent-task14-install-" + [guid]::NewGuid())
$wheelDir = Join-Path $auditRoot 'wheel'
$venvDir = Join-Path $auditRoot 'venv'
New-Item -ItemType Directory -Path $wheelDir | Out-Null
.\.venv\Scripts\python.exe -m pip wheel --no-deps --no-build-isolation --wheel-dir $wheelDir .
.\.venv\Scripts\python.exe -m venv $venvDir
$wheels = @(Get-ChildItem -LiteralPath $wheelDir -Filter 'coding_agent-*.whl')
if ($wheels.Count -ne 1) { throw "expected one project wheel, found $($wheels.Count)" }
$wheel = $wheels[0]
& (Join-Path $venvDir 'Scripts\python.exe') -m pip install --no-index --no-deps $wheel.FullName
& (Join-Path $venvDir 'Scripts\coding-agent.exe') --help
```

Expected: every command exits `0`; exactly one project wheel exists; console help works from the clean venv. Run `pip check` in the project venv for the fully installed development environment:

```powershell
.\.venv\Scripts\python.exe -m pip check
```

Expected: exit `0`. Report that the clean audit intentionally used `--no-deps` to stay offline and therefore proves project wheel/entry-point installation, while dependency integrity is proven separately by `pip check` in the accepted environment.

Check missing-key and unsafe-verify failures without printing any secret:

```powershell
$savedKey = $env:OPENAI_API_KEY
try {
    Remove-Item Env:OPENAI_API_KEY -ErrorAction SilentlyContinue
    .\.venv\Scripts\coding-agent.exe 'inspect the demo' --workspace examples\broken_pytest_project --model offline-placeholder
    if ($LASTEXITCODE -ne 2) { throw 'missing-key path did not exit 2' }
} finally {
    if ($null -ne $savedKey) { $env:OPENAI_API_KEY = $savedKey }
}

$savedKey = $env:OPENAI_API_KEY
try {
    $env:OPENAI_API_KEY = 'test-placeholder-not-a-real-credential'
    .\.venv\Scripts\coding-agent.exe 'inspect the demo' --workspace examples\broken_pytest_project --model offline-placeholder --verify 'powershell -NoProfile'
    if ($LASTEXITCODE -ne 2) { throw 'unsafe verify path did not exit 2' }
} finally {
    if ($null -eq $savedKey) { Remove-Item Env:OPENAI_API_KEY -ErrorAction SilentlyContinue } else { $env:OPENAI_API_KEY = $savedKey }
}
```

Expected: both exit `2` before model/client/network construction; output contains no key value or unsafe command echo.

**Acceptance:** Package, console script, config failure, and startup safety work from real entry points without network access.

---

### Task 10: Final fresh verification and audit matrix

**Files:** Verification only. Task 14 remains `进行中`.

#### 10.1 Focused documents and integration

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_docs.py -q -p no:cacheprovider
.\.venv\Scripts\python.exe -m pytest tests\integration -q -p no:cacheprovider
```

#### 10.2 Windows path/reparse and process tree

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_path_safety.py -k "symlink or junction or reparse or dangling or protected or outside" -q -p no:cacheprovider
.\.venv\Scripts\python.exe -m pytest tests\tools\test_shell_tool.py -k "process_tree or cleanup or timeout or truncat or environment or shell_false" -q -p no:cacheprovider
```

Expected: exit `0` with no permanent skip/xfail replacing target Windows behavior.

#### 10.3 Full suite

```powershell
$fullTemp = Join-Path ([System.IO.Path]::GetTempPath()) ("coding-agent-task14-final-" + [guid]::NewGuid())
$env:PYTHONDONTWRITEBYTECODE = '1'
.\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider --basetemp $fullTemp
```

Expected: exit `0`; report fresh pass/fail/skip/warning counts, not the planning baseline count.

#### 10.4 Supported static/source checks

No formatter, linter, or type checker is declared by `pyproject.toml`; do not invent one. Run only supported checks:

```powershell
.\.venv\Scripts\python.exe -c "import ast,pathlib; files=sorted(pathlib.Path('src').rglob('*.py'))+sorted(pathlib.Path('tests').rglob('*.py')); [ast.parse(p.read_text(encoding='utf-8'), filename=str(p)) for p in files]; print(f'AST parsed {len(files)} Python files')"
.\.venv\Scripts\python.exe -m pip check
git diff --check
```

#### 10.5 OpenAI adapter and SDK isolation audit

```powershell
rg -n "^(from|import) openai" src tests
rg -n "responses\.create|store=False|max_retries=0|include=\[\"reasoning\.encrypted_content\"\]" src\coding_agent\openai_client.py
rg -n "chat\.completions|previous_response_id|conversation=" src\coding_agent
.\.venv\Scripts\python.exe -m pytest tests\test_openai_client.py tests\test_model.py -q -p no:cacheprovider
```

Expected: production OpenAI import only in `openai_client.py`; required Responses facts present; forbidden server-state/Chat calls absent; tests exit `0` and remain fake-SDK/offline.

#### 10.6 Credentials, privacy, dependency, framework, and unfinished scans

```powershell
$scan = Get-ChildItem -Path src,tests,docs -Recurse -File
$scan += Get-Item README.md,README.txt,AGENTS.md,DESIGN.md,TASKS.md,pyproject.toml,.gitignore
$credentials = $scan | Select-String -Pattern 'sk-[A-Za-z0-9_-]{16,}|Bearer\s+[A-Za-z0-9._-]{12,}|OPENAI_API_KEY\s*=\s*["''][^<][^"'']{8,}'
if ($credentials) { $credentials; throw 'credential-like content found' }
$personal = Get-Item README.md,README.txt,docs\USAGE.md,docs\OPENAI_API.md | Select-String -Pattern '[A-Za-z]:\\Users\\|[A-Za-z]:\\code\\|/home/[^/]+/'
if ($personal) { $personal; throw 'personal absolute path found in public docs' }
$frameworks = Get-ChildItem -Path src,tests -Recurse -File | Select-String -Pattern 'langchain|llamaindex|llama_index|autogen|crewai|openai agents sdk|agent sdk'
if ($frameworks) { $frameworks; throw 'prohibited agent framework found' }
rg -n "TO[D]O|TB[D]|NotImplementedError" src tests docs README.md README.txt
rg -n "pytest\.skip|pytest\.xfail|@pytest\.mark\.(skip|xfail)" tests
git diff -- pyproject.toml
```

Expected: no real-looking credential, personal path, prohibited framework, unfinished implementation marker, unjustified suppression, or dependency diff. Any legitimate phrase in a design/plan is manually classified and reported; it is not silently ignored.

#### 10.7 README metrics and documentation links

Run the exact metric command from Task 5 and the complete document suite again. Expected: total Unicode `<= 850`, Han `<= 1000`, all links/references/options/tools/env/API facts green.

#### 10.8 Git and complete diff

```powershell
git diff --check
git status --short --untracked-files=all
git diff --stat
git diff -- README.md README.txt docs\USAGE.md docs\OPENAI_API.md tests\test_docs.py TASKS.md
git diff
```

Expected: only the approved Task14 plan, status/scope update, public docs, document tests, and exact user-approved finding files are changed; nothing staged. Review every diff line. Do not stage, commit, push, or run a remote operation.

---

## 7. Final acceptance matrix

| Requirement | Fresh evidence |
| --- | --- |
| Whole repository, not only Task13 diff, reviewed | Six batch reports plus complete findings/no-finding records |
| Findings are evidence-backed | Exact template with location, command, observed/expected result, impact, test |
| Critical/Important approval gate | Explicit stop before Task 2/3 |
| Minor changes require explicit approval | Conditional modification set |
| No uncontrolled refactor | One finding per RED/GREEN and exact allowed files |
| Agent loop self-implemented; no framework | Batch A import/dependency scan and architecture review |
| Provider-neutral core and SDK isolation | Batch A plus 10.5 |
| State/verification cannot falsely succeed | Batch C and verification/Agent suites |
| Budget/counter exact-limit behavior | Batch C focused selection |
| Message/call/continuation legality | Batch B tests and source review |
| Workspace and command safety | Batch D, reparse matrix, command matrix |
| Windows process-tree/output bounds | Batch D and 10.2 |
| Logs/reports/CLI lifecycle accurate | Batch E suites and diff review |
| `README.txt` exact name and conservative limit | PDF evidence, doc test, metric report |
| Repository URL/run/features included | `test_readme_txt_meets_submission_contract` |
| Detailed first-user guide | `test_usage_matches_parser_tools_exit_codes_and_log_path` |
| Detailed Responses API guide | API contract test plus 10.5 |
| No unsupported provider claims | Explicit unsupported-feature table test |
| Public docs have valid links/source paths | link/reference contract test |
| No key/personal path/privacy leak | doc test plus 10.6 scans |
| Clean package and console entry | Task 9 offline wheel/venv check |
| Missing key and unsafe verify fail before model | Task 9 real-entry checks |
| Offline demo | integration repair test |
| All Task1–13 behavior regresses green | Task 10.3 full suite |
| Only project-supported static checks | AST parse, pip check, diff check |
| No video/ZIP/release/remote scope | exclusion audit and final diff |
| Task14 remains reviewable | `TASKS.md` shows only Task14 `进行中`; no commit/stage/push |

If any row lacks fresh evidence, report the exact gap, leave Task 14 `进行中`, and do not claim completion.

---

## 8. Final report and stop point

After all approved work and verification, report:

1. reviewed file/module batches and evidence commands;
2. complete findings list with final disposition;
3. every approved fix's RED/GREEN/regression evidence;
4. files added/modified;
5. `README.txt` five metrics and PDF-limit interpretation;
6. documentation contract counts;
7. clean-wheel/venv install results;
8. CLI help, missing-key, and unsafe-verify results;
9. offline demo and full-suite pass/fail/skip/warning counts;
10. Windows reparse/junction/symlink and process-tree results;
11. OpenAI Responses/source/SDK-isolation audit;
12. credential/privacy/dependency/framework/suppression audits;
13. accepted limitations, including no OS sandbox and residual TOCTOU threat model;
14. any deviation or unverified item;
15. final `git status` and exact diff scope.

Then stop. Keep Task 14 `进行中`; do not stage, commit, push, create submission files, plan video, or start another task.

---

## 9. Plan self-review

- The plan reviews all Task 1–13 modules and tests, not only the latest diff.
- Every finding requires exact evidence and no finding quota exists.
- The read-only phase cannot edit code, tests, docs, or task statuses.
- Core code is writable only through an explicitly approved finding-specific allowlist.
- Every approved behavior fix uses systematic debugging and RED/GREEN/full regression.
- The PDF-derived `README.txt` name and 1000-Han limit are preserved; the automated total-character limit is stricter at 850.
- CLI commands come from the actual parser and entry point; the offline demo is a real existing integration test.
- API documentation is bounded by accepted Task9 source/tests and current official OpenAI references.
- The plan never claims custom endpoints, Azure, other providers, proxies, conversations, streaming, or async support.
- Secret, personal-path, continuation, encrypted-reasoning, and provider-body boundaries are audited.
- No new dependency, networked automated test, Agent framework, branch, worktree, subagent, stage, commit, push, pull, fetch, video, ZIP, release, or upload is included.
- The plan contains no unresolved placeholder and ends at a user review stop with Task 14 still in progress.

# Declarative Skill Catalog Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. Do not dispatch subagents unless the user explicitly authorizes them in the execution request.

**Goal:** Add deterministic local declarative Skill discovery, ordered per-session selection, and immutable per-run instruction snapshots without allowing Skills to change Agent capabilities or deterministic policy.

**Architecture:** A new provider-neutral `SkillCatalog` scans one user root and one workspace root, parses restricted `SKILL.md` documents, and resolves an ordered selection into a frozen in-memory bundle. SQLite relationship tables persist session Skill IDs and safe run snapshot metadata, while `SessionController` owns selection lifecycle and passes only the frozen bundle into the existing instruction builder.

**Tech Stack:** Python 3.11+, standard library (`dataclasses`, `enum`, `hashlib`, `os`, `pathlib`, `re`, `sqlite3`), existing project modules, pytest, Windows filesystem behavior.

**Spec:** `docs/superpowers/specs/2026-08-29-declarative-skill-catalog-design.md`

**Approved execution amendment (2026-08-30):** Task 0 review found that the
original Task 4 depended on `SessionRunRequest.skill_bundle` before its TDD
cycle. The request-carrier cycle is therefore Task 3A and must finish before
Task 4. This amendment also locks catalog-unavailable semantics, exact newline
parsing, parent/corrupt-row store behavior, compatibility-test-double updates,
system-temporary pytest roots, and explicit review of untracked new files. These
rules replace conflicting older wording in this plan.

## Global Constraints

- Work only in the current main workspace. Do not create a branch or Git worktree.
- Do not dispatch a subagent or parallel agent unless the current execution request explicitly authorizes it.
- Do not stage, commit, push, pull, fetch, or access a remote repository before the user reviews the completed milestone and explicitly authorizes the action.
- Task21 remains `进行中` at the final review stop. Do not start Task22 or Task23.
- Do not add a production or test dependency. `pyproject.toml` must remain unchanged.
- Do not call a real model endpoint, read a real API key, or allow automated tests to access the network.
- Do not add executable Skills, plugin loading, Python imports from a catalog, MCP, remote download, a marketplace, HTTP/SSE, or GUI behavior.
- Do not modify message types, model clients, `AgentRunner`, Agent state, tools, Task8 safety enforcement, Task10 termination, Task11 verification, Task12 logging/reporting, CLI, or configuration.
- Preserve `ModelClient.complete(ModelRequest) -> ModelResponse`, existing provider behavior, all tool schemas, the single-active-run controller, and the Task11-only success path.
- Each raw `SKILL.md` is limited to 65,536 bytes. The final combined selected Skill text is independently limited to 65,536 UTF-8 bytes.
- Full Skill instructions remain in immutable in-memory objects only. Never persist or log bodies, combined prompt text, absolute paths, front matter text, or raw filesystem exceptions.
- All new tests use pytest temporary directories and explicitly injected catalog roots. They do not inspect the developer's real `%LOCALAPPDATA%` catalog.
- Every pytest `--basetemp` is outside the repository under `$env:TEMP\coding-agent-task21-pytest\<unique-step-name>`. Never reuse the same child concurrently and never create a repository-local `.pytest-tmp` directory.
- Follow strict RED, GREEN, related regression order for every production behavior. A RED that passes or fails for an unplanned reason stops that cycle.
- Use `superpowers:systematic-debugging` before changing code in response to a reproducible unexpected failure.
- Use `superpowers:verification-before-completion` before presenting final verification results.

---

## Locked File Map

### Create

- `src/coding_agent/skills.py` — Skill value types, restricted parser, two-root discovery, safe diagnostics, ordered selection resolution, and production root construction.
- `tests/test_skills.py` — parser, catalog, selection, safety, privacy, and offline tests.

### Modify

- `src/coding_agent/session_store.py` — schema v2, ordered session selection rows, safe run snapshot rows, and atomic store operations.
- `src/coding_agent/session_runtime.py` — hidden optional Skill bundle on `SessionRunRequest` and propagation to application execution.
- `src/coding_agent/session_controller.py` — catalog dependency, catalog query API, first-run selection, idle replacement, and per-run resolution.
- `src/coding_agent/app.py` — additive hidden Skill-instruction input to `execute_agent_run()` and use of the existing `RunInstructionBuilder` parameter.
- `tests/test_session_store.py` — migration, persistence, order, rollback, and no-body tests.
- `tests/test_session_runtime.py` — request invariants, hidden representation, and executor propagation tests.
- `tests/test_session_controller.py` — selection lifecycle, admission, failure atomicity, and immutable-active-run tests.
- `tests/test_app.py` — final instruction mapping and no-selection compatibility tests.
- `DESIGN.md` — only the approved Task21 Skill-baseline amendment made before production TDD.
- `docs/superpowers/specs/2026-08-29-declarative-skill-catalog-design.md` — only the approved review amendments made before production TDD.
- `docs/superpowers/plans/2026-08-29-declarative-skill-catalog.md` — this approved execution amendment.
- `TASKS.md` — only Task20 and Task21 status values during Task 0.

### Keep Unchanged

- `src/coding_agent/messages.py`
- `src/coding_agent/model.py`
- `src/coding_agent/openai_client.py`
- `src/coding_agent/chat_completions_client.py`
- `src/coding_agent/agent.py`
- `src/coding_agent/state.py`
- `src/coding_agent/context.py`
- `src/coding_agent/termination.py`
- `src/coding_agent/verification.py`
- `src/coding_agent/safety.py`
- `src/coding_agent/tools/**`
- `src/coding_agent/logging.py`
- `src/coding_agent/report.py`
- `src/coding_agent/cli.py`
- `src/coding_agent/config.py`
- `src/coding_agent/instructions.py`
- `pyproject.toml`
- existing tests other than the four test files listed under “Modify”

If implementation requires changing a keep-unchanged file, public signature, schema decision, or dependency, stop and request a design amendment.

## Locked Interfaces and Invariants

`src/coding_agent/skills.py` produces these public interfaces:

```python
class SkillSource(StrEnum):
    USER = "user"
    WORKSPACE = "workspace"


@dataclass(frozen=True, slots=True)
class SkillDescriptor:
    skill_id: str
    name: str
    description: str
    source: SkillSource
    sha256: str
    char_count: int


@dataclass(frozen=True, slots=True)
class SkillCatalogDiagnostic:
    code: str
    source: SkillSource
    entry_name: str


@dataclass(frozen=True, slots=True)
class SkillCatalogView:
    skills: tuple[SkillDescriptor, ...]
    diagnostics: tuple[SkillCatalogDiagnostic, ...]
    usable: bool


@dataclass(frozen=True, slots=True)
class SkillInstructionSnapshot:
    descriptor: SkillDescriptor
    instructions: str = field(repr=False)


@dataclass(frozen=True, slots=True)
class SkillInstructionBundle:
    items: tuple[SkillInstructionSnapshot, ...]
    text: str = field(repr=False)
    sha256: str
    char_count: int


@dataclass(frozen=True, slots=True)
class RunSkillSnapshotMetadata:
    skill_id: str
    source: SkillSource
    sha256: str
    char_count: int


class SkillCatalogError(RuntimeError):
    code: str


class SkillCatalog:
    def __init__(
        self,
        *,
        user_root: Path,
        workspace_root: Path,
    ) -> None: ...

    @property
    def workspace_root(self) -> Path: ...

    @classmethod
    def from_environment(
        cls,
        workspace: Path,
        *,
        environ: Mapping[str, str] | None = None,
    ) -> SkillCatalog: ...

    def discover(self) -> SkillCatalogView: ...

    def resolve(
        self,
        skill_ids: tuple[str, ...],
    ) -> SkillInstructionBundle | None: ...
```

`RunSkillSnapshotMetadata` is the safe auxiliary record required by the approved schema's read API. It contains exactly the columns persisted per selected Skill and never contains `name`, `description`, instructions, or a path.

`from_environment()` preserves the approved explicit constructor while giving production composition a deterministic way to represent a missing `LOCALAPPDATA` source as `catalog_root_unavailable`. It does not create a fallback directory. Passing explicit roots remains the only path used by unit tests. A missing directory is an empty readable source; a missing environment root, present non-directory, unreadable root, or unsafe root-level reparse point makes `SkillCatalogView.usable` false. Empty selection still returns `None`; every non-empty selection then raises `skill_catalog_unavailable`, even if the ID is visible in the other source. With both sources readable, a missing ID raises `selected_skill_unavailable`.

`SessionStore` gains:

```python
def get_skill_selection(self, session_id: str) -> tuple[str, ...]: ...

def replace_skill_selection(
    self,
    session_id: str,
    skill_ids: tuple[str, ...],
) -> tuple[str, ...]: ...

def get_run_skill_snapshots(
    self,
    run_id: str,
) -> tuple[RunSkillSnapshotMetadata, ...]: ...
```

The existing store creation methods receive backward-compatible keywords:

```python
def create_session(
    self,
    message: str,
    *,
    selected_skills: tuple[SkillDescriptor, ...] = (),
) -> SessionSubmission: ...

def submit_message(
    self,
    session_id: str,
    message: str,
    *,
    selected_skills: tuple[SkillDescriptor, ...] = (),
) -> SessionSubmission: ...
```

`SessionController` gains the methods approved in the spec, while
`SessionController.__init__()` and `SessionController.open()` receive an optional
keyword-only `skill_catalog: SkillCatalog | None = None`. When omitted,
production catalog construction uses `SkillCatalog.from_environment()`.

`SessionRunRequest` gains:

```python
skill_bundle: SkillInstructionBundle | None = field(default=None, repr=False)
```

`execute_agent_run()` gains:

```python
skill_instructions: str | None = None
```

No other public signature changes.

---

### Task 0: Baseline, Approved Documents, and Task Status

**Files:**
- Read: `AGENTS.md`
- Read: `DESIGN.md`
- Read: `TASKS.md`
- Read: `docs/superpowers/specs/2026-08-29-declarative-skill-catalog-design.md`
- Read: `docs/superpowers/plans/2026-08-29-declarative-skill-catalog.md`
- Read: every file in the locked file map before editing it
- Modify: `TASKS.md`, status values only

**Interfaces:**
- Consumes: accepted Task20 implementation at repository HEAD.
- Produces: a verified Task1–Task20 baseline with Task20 `已完成` and Task21 `进行中`.

- [ ] **Step 1: Verify repository identity and working tree**

Run:

```powershell
git rev-parse --show-toplevel
git branch --show-current
git log -3 --oneline
git status --short --untracked-files=all
git diff --check
```

Expected: root is `D:\code\coding_agent`; branch is `main`; HEAD is the user-accepted Task20 commit; `git diff --check` exits `0`; the only permitted uncommitted paths are the approved Task21 design and plan documents if the user has not committed them. Any other path stops execution.

- [ ] **Step 2: Read the complete baseline**

Run:

```powershell
Get-Content -Raw AGENTS.md
Get-Content -Raw DESIGN.md
Get-Content -Raw TASKS.md
Get-Content -Raw docs\superpowers\specs\2026-08-29-declarative-skill-catalog-design.md
Get-Content -Raw docs\superpowers\plans\2026-08-29-declarative-skill-catalog.md
Get-Content -Raw src\coding_agent\instructions.py
Get-Content -Raw src\coding_agent\session.py
Get-Content -Raw src\coding_agent\session_store.py
Get-Content -Raw src\coding_agent\session_runtime.py
Get-Content -Raw src\coding_agent\session_controller.py
Get-Content -Raw src\coding_agent\app.py
Get-Content -Raw tests\test_instructions.py
Get-Content -Raw tests\test_session_store.py
Get-Content -Raw tests\test_session_runtime.py
Get-Content -Raw tests\test_session_controller.py
Get-Content -Raw tests\test_app.py
```

Expected: actual interfaces match the locked map; `RunInstructionBuilder.build()` already accepts `skill_instructions`; schema version is 1; Task20 is still recorded as `进行中` and Task21 as `未开始`. Any public-interface conflict stops execution.

- [ ] **Step 3: Run the complete pre-Task21 baseline**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider --basetemp "$env:TEMP\coding-agent-task21-pytest\task21-baseline"
```

Expected: exit `0`; all collected Task1–Task20 tests pass; no skip or xfail replaces Windows reparse, junction, symlink, timeout, or process-tree coverage. Record the real pass, fail, skip, warning, and duration output.

- [ ] **Step 4: Update only the two task status values**

Edit `TASKS.md` so Task20 changes from `进行中` to `已完成` and Task21 changes from `未开始` to `进行中`. Do not change prose or any other task.

Run:

```powershell
$text = Get-Content -Raw TASKS.md
$matches = [regex]::Matches($text, '`进行中`')
if ($matches.Count -ne 1) { throw "expected exactly one in-progress task, found $($matches.Count)" }
Get-Content TASKS.md | Select-Object -Skip 820 -First 60
git diff --check
```

Expected: exit `0`; Task20 is `已完成`; Task21 is the only `进行中` task; no production or test file changed.

---

### Task 1: Skill Value Types, Restricted Parser, and Deterministic Discovery

**Files:**
- Create: `src/coding_agent/skills.py`
- Create: `tests/test_skills.py`

**Interfaces:**
- Consumes: `Path`, Python UTF-8 decoding, frozen dataclass conventions used by the repository.
- Produces: `SkillSource`, `SkillDescriptor`, `SkillCatalogDiagnostic`, `SkillCatalogView`, `SkillInstructionSnapshot`, `SkillInstructionBundle`, `RunSkillSnapshotMetadata`, `SkillCatalogError`, and the discovery half of `SkillCatalog`.

- [ ] **Step 1: Write the first RED tests for a valid catalog and empty roots**

Create `tests/test_skills.py` with the imports, helper, and tests below:

```python
from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from coding_agent.skills import SkillCatalog, SkillSource


def write_skill(
    root: Path,
    skill_id: str,
    body: str,
    *,
    name: str | None = None,
    description: str = "Deterministic local instructions.",
    bom: bool = False,
    newline: str = "\n",
) -> Path:
    directory = root / skill_id
    directory.mkdir(parents=True, exist_ok=True)
    text = newline.join(
        (
            "---",
            f"id: {skill_id}",
            f"name: {name or skill_id.replace('-', ' ').title()}",
            f"description: {description}",
            "---",
            body,
        )
    )
    encoded = text.encode("utf-8")
    if bom:
        encoded = b"\xef\xbb\xbf" + encoded
    path = directory / "SKILL.md"
    path.write_bytes(encoded)
    return path


def test_missing_catalog_roots_are_empty(tmp_path: Path) -> None:
    catalog = SkillCatalog(
        user_root=tmp_path / "missing-user",
        workspace_root=tmp_path / "missing-workspace",
    )
    view = catalog.discover()
    assert view.skills == ()
    assert view.diagnostics == ()
    assert view.usable is True


def test_valid_skills_are_normalized_hashed_and_stably_sorted(
    tmp_path: Path,
) -> None:
    user_root = tmp_path / "user"
    workspace_root = tmp_path / "workspace"
    write_skill(workspace_root, "zeta", "line one\r\nline two\r\n")
    write_skill(user_root, "alpha", "  first\rsecond  ", bom=True)
    catalog = SkillCatalog(
        user_root=user_root,
        workspace_root=workspace_root,
    )
    first = catalog.discover()
    second = catalog.discover()
    assert first == second
    assert [item.skill_id for item in first.skills] == ["alpha", "zeta"]
    assert [item.source for item in first.skills] == [
        SkillSource.USER,
        SkillSource.WORKSPACE,
    ]
    assert first.skills[0].char_count == len("first\nsecond")
    assert first.skills[0].sha256 == hashlib.sha256(
        b"first\nsecond"
    ).hexdigest()
    assert first.diagnostics == ()
    assert first.usable is True


def test_newline_normalization_is_exact_and_preserves_unicode_nel(
    tmp_path: Path,
) -> None:
    root = tmp_path / "user"
    write_skill(root, "unicode-lines", "first\u0085second\r\nthird\rfourth")
    descriptor = SkillCatalog(
        user_root=root,
        workspace_root=tmp_path / "workspace",
    ).discover().skills[0]
    normalized = "first\u0085second\nthird\nfourth"
    assert descriptor.char_count == len(normalized)
    assert descriptor.sha256 == hashlib.sha256(normalized.encode("utf-8")).hexdigest()
```

- [ ] **Step 2: Run the first RED**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_skills.py -k "missing_catalog_roots or valid_skills or newline_normalization" -q -p no:cacheprovider --basetemp "$env:TEMP\coding-agent-task21-pytest\task21-skill-discovery-red"
```

Expected: nonzero exit because `coding_agent.skills` does not exist. A syntax error, fixture error, or failure in existing code is not an acceptable RED. The GREEN rerun must also include `test_newline_normalization_is_exact_and_preserves_unicode_nel`.

- [ ] **Step 3: Add the minimal public types and valid-file discovery**

Create `src/coding_agent/skills.py` with:

- constants `MAX_SKILL_FILE_BYTES = 65_536` and `MAX_SELECTED_SKILL_BYTES = 65_536`;
- the exact public types in “Locked Interfaces and Invariants”;
- self-validation for enum identity, ID syntax, non-empty bounded metadata, 64-lowercase-hex SHA-256, and exact character counts;
- `_normalize_body()` that converts only CRLF and CR to LF and strips outer whitespace;
- `_read_definition(path, source, entry_name)` that reads at most 65,537 bytes once, decodes `utf-8-sig`, validates decoded controls before any line parsing, validates the restricted front matter, and returns one immutable internal definition;
- `SkillCatalog.discover()` that scans immediate children, parses valid entries, sorts descriptors, and returns an empty usable view for missing roots.

The first implementation must not add `resolve()` behavior beyond returning `None` for an empty tuple and raising `SkillCatalogError("invalid_skill_selection")` for any non-empty input; Task 2 owns selection resolution.

Use this exact front-matter split rule; `splitlines()` is forbidden because it
would reinterpret `VT`, `FF`, `NEL`, `U+2028`, and `U+2029` as line separators:

```python
_validate_decoded_controls(decoded)
normalized_text = decoded.replace("\r\n", "\n").replace("\r", "\n")
lines = normalized_text.split("\n")
if not lines or lines[0] != "---":
    raise _EntryError("invalid_skill_front_matter")
try:
    closing = lines.index("---", 1)
except ValueError:
    raise _EntryError("invalid_skill_front_matter") from None
metadata_lines = lines[1:closing]
body = _normalize_body("\n".join(lines[closing + 1 :]))
```

Each metadata line is split on the first colon. Reject whitespace-altered keys, unknown keys, duplicates, missing values, multiline continuation syntax, and missing required keys. Do not use a YAML library.

- [ ] **Step 4: Run GREEN and existing instruction regression**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_skills.py -k "missing_catalog_roots or valid_skills or newline_normalization" -q -p no:cacheprovider --basetemp "$env:TEMP\coding-agent-task21-pytest\task21-skill-discovery-green"
.\.venv\Scripts\python.exe -m pytest tests\test_instructions.py tests\test_session_store.py tests\test_session_runtime.py tests\test_session_controller.py -q -p no:cacheprovider --basetemp "$env:TEMP\coding-agent-task21-pytest\task21-skill-discovery-regression"
```

Expected: both commands exit `0`; report actual test counts. No existing module imports the provider SDK because of `skills.py`.

- [ ] **Step 5: Write RED tests for malformed entries and safe diagnostics**

Append parameterized tests that replace the valid bytes with exact malformed cases:

```python
@pytest.mark.parametrize(
    ("entry_name", "content", "expected_code"),
    (
        ("Bad_ID", b"---\nid: Bad_ID\nname: Bad\ndescription: bad\n---\nbody", "invalid_entry_name"),
        ("missing-file", None, "missing_skill_file"),
        ("bad-front", b"id: bad-front\nbody", "invalid_skill_front_matter"),
        ("missing-field", b"---\nid: missing-field\nname: Missing\n---\nbody", "invalid_skill_front_matter"),
        ("empty-name", b"---\nid: empty-name\nname: \ndescription: x\n---\nbody", "invalid_skill_metadata"),
        ("long-name", ("---\nid: long-name\nname: " + "n" * 81 + "\ndescription: x\n---\nbody").encode("utf-8"), "invalid_skill_metadata"),
        ("long-description", ("---\nid: long-description\nname: Long\ndescription: " + "d" * 241 + "\n---\nbody").encode("utf-8"), "invalid_skill_metadata"),
        ("multiline", b"---\nid: multiline\nname: Multi\ndescription: first\n  second\n---\nbody", "invalid_skill_front_matter"),
        ("unknown", b"---\nid: unknown\nname: Unknown\ndescription: x\nversion: 1\n---\nbody", "invalid_skill_front_matter"),
        ("duplicate", b"---\nid: duplicate\nname: One\nname: Two\ndescription: x\n---\nbody", "invalid_skill_front_matter"),
        ("mismatch", b"---\nid: other\nname: Other\ndescription: x\n---\nbody", "skill_id_mismatch"),
        ("empty-body", b"---\nid: empty-body\nname: Empty\ndescription: x\n---\n \n", "empty_skill_instructions"),
        ("control", b"---\nid: control\nname: Control\ndescription: x\n---\nbody\x00", "invalid_skill_instructions"),
        ("vt-control", b"---\nid: vt-control\nname: Control\ndescription: x\n---\nbody\x0bnext", "invalid_skill_instructions"),
        ("ff-control", b"---\nid: ff-control\nname: Control\ndescription: x\n---\nbody\x0cnext", "invalid_skill_instructions"),
        ("del-control", b"---\nid: del-control\nname: Control\ndescription: x\n---\nbody\x7fnext", "invalid_skill_instructions"),
    ),
)
def test_malformed_entry_is_isolated_with_safe_diagnostic(
    tmp_path: Path,
    entry_name: str,
    content: bytes | None,
    expected_code: str,
) -> None:
    user_root = tmp_path / "user"
    write_skill(user_root, "valid", "safe body")
    directory = user_root / entry_name
    directory.mkdir(parents=True, exist_ok=True)
    if content is not None:
        (directory / "SKILL.md").write_bytes(content)
    view = SkillCatalog(
        user_root=user_root,
        workspace_root=tmp_path / "workspace",
    ).discover()
    assert [item.skill_id for item in view.skills] == ["valid"]
    assert [(item.code, item.source, item.entry_name) for item in view.diagnostics] == [
        (expected_code, SkillSource.USER, entry_name)
    ]
    rendered = repr(view.diagnostics)
    assert str(tmp_path) not in rendered
    assert "safe body" not in rendered
    assert view.usable is True


def test_invalid_utf8_and_first_byte_over_limit_are_rejected(
    tmp_path: Path,
) -> None:
    root = tmp_path / "user"
    exact_directory = root / "exact"
    exact_directory.mkdir(parents=True)
    exact_prefix = b"---\nid: exact\nname: Exact\ndescription: x\n---\n"
    (exact_directory / "SKILL.md").write_bytes(
        exact_prefix + b"x" * (65_536 - len(exact_prefix))
    )
    for skill_id, raw, code in (
        ("bad-utf8", b"\xff\xfe", "skill_file_not_utf8"),
        ("too-large", b"x" * 65_537, "skill_file_too_large"),
    ):
        directory = root / skill_id
        directory.mkdir(parents=True)
        (directory / "SKILL.md").write_bytes(raw)
    view = SkillCatalog(
        user_root=root,
        workspace_root=tmp_path / "workspace",
    ).discover()
    assert [item.skill_id for item in view.skills] == ["exact"]
    assert [(item.entry_name, item.code) for item in view.diagnostics] == [
        ("bad-utf8", "skill_file_not_utf8"),
        ("too-large", "skill_file_too_large"),
    ]


def test_skill_id_boundaries_are_exact(tmp_path: Path) -> None:
    root = tmp_path / "user"
    valid_id = "a" * 64
    write_skill(root, valid_id, "valid maximum id")
    for invalid_id in ("-leading", "trailing-", "a" * 65):
        directory = root / invalid_id
        directory.mkdir(parents=True)
        (directory / "SKILL.md").write_text(
            "---\n"
            f"id: {invalid_id}\n"
            "name: Boundary\n"
            "description: x\n"
            "---\n"
            "body",
            encoding="utf-8",
        )
    view = SkillCatalog(
        user_root=root,
        workspace_root=tmp_path / "workspace",
    ).discover()
    assert [item.skill_id for item in view.skills] == [valid_id]
    assert [item.entry_name for item in view.diagnostics] == [
        "-leading",
        "a" * 65,
        "trailing-",
    ]
    assert all(item.code == "invalid_entry_name" for item in view.diagnostics)


def test_public_skill_metadata_types_reject_invalid_construction() -> None:
    from coding_agent.skills import RunSkillSnapshotMetadata, SkillDescriptor

    with pytest.raises(TypeError):
        SkillDescriptor(
            "valid",
            "Valid",
            "safe",
            "user",  # type: ignore[arg-type]
            "0" * 64,
            1,
        )
    with pytest.raises(ValueError):
        SkillDescriptor(
            "valid",
            "Valid",
            "safe",
            SkillSource.USER,
            "not-a-hash",
            1,
        )
    with pytest.raises(ValueError):
        RunSkillSnapshotMetadata(
            "valid",
            SkillSource.USER,
            "0" * 64,
            0,
        )
```

- [ ] **Step 6: Run malformed-entry RED**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_skills.py -k "malformed or invalid_utf8 or skill_id_boundaries or public_skill_metadata" -q -p no:cacheprovider --basetemp "$env:TEMP\coding-agent-task21-pytest\task21-skill-invalid-red"
```

Expected: nonzero exit because the minimal parser does not yet emit all locked diagnostic codes and isolation behavior.

- [ ] **Step 7: Implement exact diagnostics and isolation**

Add a private `_EntryError(code)` whose string representation is never surfaced. For each root:

1. treat absence as an empty source;
2. emit `catalog_root_unavailable` with `entry_name="<catalog>"` for a present non-directory or an unreadable root;
3. sort child names before parsing;
4. emit one diagnostic per invalid entry;
5. retain all unambiguous valid definitions;
6. sort diagnostics by `(source.value, entry_name, code)`.

Reject metadata values containing forbidden controls. Preserve no raw exception object beyond the local `except OSError` block.

- [ ] **Step 8: Run malformed-entry GREEN and Task20 regression**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_skills.py -k "malformed or invalid_utf8 or skill_id_boundaries or public_skill_metadata" -q -p no:cacheprovider --basetemp "$env:TEMP\coding-agent-task21-pytest\task21-skill-invalid-green"
.\.venv\Scripts\python.exe -m pytest tests\test_instructions.py tests\test_session_store.py tests\test_session_runtime.py tests\test_session_controller.py tests\test_app.py -q -p no:cacheprovider --basetemp "$env:TEMP\coding-agent-task21-pytest\task21-skill-invalid-regression"
```

Expected: both commands exit `0`; report actual counts.

---

### Task 2: Conflict, Ordered Resolution, Size Limits, and Filesystem Safety

**Files:**
- Modify: `src/coding_agent/skills.py`
- Modify: `tests/test_skills.py`

**Interfaces:**
- Consumes: Task 1 catalog definitions and safe diagnostics.
- Produces: complete `SkillCatalog.resolve()` behavior and immutable private instruction bodies.

- [ ] **Step 1: Write RED tests for cross-source conflicts and ordered resolution**

Append:

```python
from coding_agent.skills import SkillCatalogError


def test_duplicate_id_across_sources_has_no_precedence(tmp_path: Path) -> None:
    user_root = tmp_path / "user"
    workspace_root = tmp_path / "workspace"
    write_skill(user_root, "review", "user body")
    write_skill(workspace_root, "review", "workspace body")
    catalog = SkillCatalog(user_root=user_root, workspace_root=workspace_root)
    view = catalog.discover()
    assert view.skills == ()
    assert view.usable is False
    assert [(item.source, item.entry_name, item.code) for item in view.diagnostics] == [
        (SkillSource.USER, "review", "duplicate_skill_id"),
        (SkillSource.WORKSPACE, "review", "duplicate_skill_id"),
    ]
    with pytest.raises(SkillCatalogError) as captured:
        catalog.resolve(("review",))
    assert captured.value.code == "duplicate_skill_id"
    assert str(captured.value) == "duplicate_skill_id"
    assert str(tmp_path) not in repr(captured.value)


def test_resolve_preserves_explicit_order_and_hides_instruction_text(
    tmp_path: Path,
) -> None:
    user_root = tmp_path / "user"
    workspace_root = tmp_path / "workspace"
    write_skill(user_root, "first", "private first")
    write_skill(workspace_root, "second", "private second")
    catalog = SkillCatalog(user_root=user_root, workspace_root=workspace_root)
    assert catalog.resolve(()) is None
    bundle = catalog.resolve(("second", "first"))
    assert bundle is not None
    assert [item.descriptor.skill_id for item in bundle.items] == ["second", "first"]
    assert bundle.text == (
        "### Skill: second — Second\nprivate second\n\n"
        "### Skill: first — First\nprivate first"
    )
    assert bundle.sha256 == hashlib.sha256(bundle.text.encode("utf-8")).hexdigest()
    assert bundle.char_count == len(bundle.text)
    rendered = repr(bundle)
    assert "private first" not in rendered
    assert "private second" not in rendered
    with pytest.raises(Exception):
        bundle.items[0].instructions = "changed"  # type: ignore[misc]
```

- [ ] **Step 2: Run conflict/order RED**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_skills.py::test_duplicate_id_across_sources_has_no_precedence tests\test_skills.py::test_resolve_preserves_explicit_order_and_hides_instruction_text -q -p no:cacheprovider --basetemp "$env:TEMP\coding-agent-task21-pytest\task21-skill-resolve-red"
```

Expected: nonzero exit because Task 1 deliberately lacks non-empty resolution and duplicate-ID rejection.

- [ ] **Step 3: Implement conflict handling and ordered immutable bundles**

Implement an internal scan result that retains definition bodies with `repr=False` while exposing only descriptors and diagnostics. When a valid ID occurs in both sources:

- remove it from the public `skills` tuple;
- add one `duplicate_skill_id` diagnostic for each source;
- set `usable=False`;
- reject every non-empty `resolve()` request with `SkillCatalogError("duplicate_skill_id")`.

For an unambiguous catalog, resolve each requested ID in caller order and join exact sections with `"\n\n"`. Compute the combined SHA-256 and character count from the joined string. Frozen dataclasses and immutable strings are the only active snapshot representation.

- [ ] **Step 4: Run conflict/order GREEN and regression**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_skills.py::test_duplicate_id_across_sources_has_no_precedence tests\test_skills.py::test_resolve_preserves_explicit_order_and_hides_instruction_text -q -p no:cacheprovider --basetemp "$env:TEMP\coding-agent-task21-pytest\task21-skill-resolve-green"
.\.venv\Scripts\python.exe -m pytest tests\test_instructions.py tests\test_session_store.py tests\test_session_runtime.py tests\test_session_controller.py tests\test_app.py -q -p no:cacheprovider --basetemp "$env:TEMP\coding-agent-task21-pytest\task21-skill-resolve-regression"
```

Expected: both exit `0`; report actual counts.

- [ ] **Step 5: Write RED tests for invalid selections and exact combined-size semantics**

Append:

```python
@pytest.mark.parametrize(
    ("selection", "code"),
    (
        (["valid"], "invalid_skill_selection"),
        (("Bad_ID",), "invalid_skill_selection"),
        (("../valid",), "invalid_skill_selection"),
        (("C:\\valid",), "invalid_skill_selection"),
        (("valid:stream",), "invalid_skill_selection"),
        (("valid", "valid"), "duplicate_skill_selection"),
        (("missing",), "selected_skill_unavailable"),
    ),
)
def test_invalid_selection_has_stable_error(
    tmp_path: Path,
    selection: object,
    code: str,
) -> None:
    root = tmp_path / "user"
    write_skill(root, "valid", "body")
    catalog = SkillCatalog(user_root=root, workspace_root=tmp_path / "workspace")
    with pytest.raises(SkillCatalogError) as captured:
        catalog.resolve(selection)  # type: ignore[arg-type]
    assert captured.value.code == code


def test_combined_limit_accepts_exact_limit_and_rejects_first_byte_over(
    tmp_path: Path,
) -> None:
    root = tmp_path / "user"
    first_body = "a" * 128
    write_skill(root, "first", first_body)
    first_section = "### Skill: first — First\n" + first_body
    second_prefix = "### Skill: second — Second\n"
    second_body_size = 65_536 - len(
        (first_section + "\n\n" + second_prefix).encode("utf-8")
    )
    write_skill(root, "second", "b" * second_body_size)
    assert (root / "second" / "SKILL.md").stat().st_size <= 65_536
    catalog = SkillCatalog(user_root=root, workspace_root=tmp_path / "workspace")
    exact = catalog.resolve(("first", "second"))
    assert exact is not None
    assert len(exact.text.encode("utf-8")) == 65_536
    write_skill(root, "second", "b" * (second_body_size + 1))
    with pytest.raises(SkillCatalogError) as captured:
        catalog.resolve(("first", "second"))
    assert captured.value.code == "skill_selection_too_large"
```

The raw second file remains below 65,536 bytes because the two-Skill combined limit uses two prompt headings while the large body remains in only one file. Verify this assertion in the test helper before accepting the RED.

- [ ] **Step 6: Run invalid-selection/size RED**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_skills.py -k "invalid_selection or combined_limit" -q -p no:cacheprovider --basetemp "$env:TEMP\coding-agent-task21-pytest\task21-skill-limits-red"
```

Expected: nonzero exit because selection type, duplicate, availability, or exact byte-limit enforcement is incomplete.

- [ ] **Step 7: Implement validation in locked priority order**

Implement `resolve()` in this order:

1. require `type(skill_ids) is tuple`;
2. return `None` for the empty tuple without scanning;
3. validate every element is a string matching the exact ID regex;
4. reject duplicate IDs before filesystem access;
5. scan both sources;
6. if either source is unavailable, reject with `skill_catalog_unavailable`;
7. reject a duplicate catalog;
8. reject a missing or malformed selected ID;
9. build ordered sections;
10. encode the final combined text once and reject length greater than 65,536;
11. return the frozen bundle.

Do not truncate Skill text.

- [ ] **Step 8: Run invalid-selection/size GREEN and regression**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_skills.py -k "invalid_selection or combined_limit" -q -p no:cacheprovider --basetemp "$env:TEMP\coding-agent-task21-pytest\task21-skill-limits-green"
.\.venv\Scripts\python.exe -m pytest tests\test_instructions.py tests\test_session_store.py tests\test_session_runtime.py tests\test_session_controller.py tests\test_app.py -q -p no:cacheprovider --basetemp "$env:TEMP\coding-agent-task21-pytest\task21-skill-limits-regression"
```

Expected: both exit `0`; report actual counts.

- [ ] **Step 9: Write RED tests for symlink, junction, and unavailable-root handling**

Add `os`, `subprocess`, and `sys` imports, then add these exact Windows-focused tests:

```python
def test_symlink_skill_directory_is_rejected_without_reading_target(
    tmp_path: Path,
) -> None:
    target_root = tmp_path / "target-root"
    target_file = write_skill(target_root, "review", "private target body")
    user_root = tmp_path / "user"
    user_root.mkdir()
    link = user_root / "review"
    try:
        link.symlink_to(target_file.parent, target_is_directory=True)
    except OSError as exc:
        pytest.fail(f"target Windows environment must allow this test: {exc}")
    view = SkillCatalog(
        user_root=user_root,
        workspace_root=tmp_path / "workspace",
    ).discover()
    assert view.skills == ()
    assert [(item.entry_name, item.code) for item in view.diagnostics] == [
        ("review", "unsafe_skill_path")
    ]
    assert "private target body" not in repr(view)
    assert str(tmp_path) not in repr(view)


def test_symlink_skill_file_is_rejected_without_reading_target(
    tmp_path: Path,
) -> None:
    target = tmp_path / "private-target.md"
    target.write_text("private file target", encoding="utf-8")
    directory = tmp_path / "user" / "review"
    directory.mkdir(parents=True)
    link = directory / "SKILL.md"
    try:
        link.symlink_to(target)
    except OSError as exc:
        pytest.fail(f"target Windows environment must allow this test: {exc}")
    view = SkillCatalog(
        user_root=tmp_path / "user",
        workspace_root=tmp_path / "workspace",
    ).discover()
    assert [(item.entry_name, item.code) for item in view.diagnostics] == [
        ("review", "unsafe_skill_path")
    ]
    assert "private file target" not in repr(view)


def test_junction_catalog_root_is_rejected_without_reading_target(
    tmp_path: Path,
) -> None:
    target = tmp_path / "junction-target"
    write_skill(target, "review", "private junction body")
    junction = tmp_path / "junction-user"
    completed = subprocess.run(
        [
            "cmd.exe",
            "/d",
            "/c",
            "mklink",
            "/J",
            str(junction.resolve(strict=False)),
            str(target.resolve(strict=True)),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    try:
        view = SkillCatalog(
            user_root=junction,
            workspace_root=tmp_path / "workspace",
        ).discover()
        assert view.skills == ()
        assert [(item.source, item.entry_name, item.code) for item in view.diagnostics] == [
            (SkillSource.USER, "<catalog>", "catalog_root_unavailable")
        ]
        assert "private junction body" not in repr(view)
        assert str(target) not in repr(view)
    finally:
        os.rmdir(junction)


def test_present_non_directory_root_has_safe_diagnostic(tmp_path: Path) -> None:
    user_root = tmp_path / "user-file"
    user_root.write_text("private root content", encoding="utf-8")
    view = SkillCatalog(
        user_root=user_root,
        workspace_root=tmp_path / "workspace",
    ).discover()
    assert view.skills == ()
    assert [(item.source, item.entry_name, item.code) for item in view.diagnostics] == [
        (SkillSource.USER, "<catalog>", "catalog_root_unavailable")
    ]
    assert "private root content" not in repr(view)


def test_from_environment_uses_exact_localappdata_root(
    tmp_path: Path,
) -> None:
    local_app_data = tmp_path / "local-app-data"
    user_skills = local_app_data / "MiniCodex" / "skills"
    write_skill(user_skills, "review", "user review")
    catalog = SkillCatalog.from_environment(
        tmp_path,
        environ={"LOCALAPPDATA": str(local_app_data)},
    )
    view = catalog.discover()
    assert [(item.skill_id, item.source) for item in view.skills] == [
        ("review", SkillSource.USER)
    ]
    assert view.diagnostics == ()
    assert view.usable is True


def test_missing_localappdata_makes_nonempty_selection_unavailable(
    tmp_path: Path,
) -> None:
    workspace_skills = tmp_path / ".coding-agent" / "skills"
    write_skill(workspace_skills, "review", "workspace review")
    catalog = SkillCatalog.from_environment(tmp_path, environ={})
    view = catalog.discover()
    assert [item.skill_id for item in view.skills] == ["review"]
    assert [item.source for item in view.skills] == [SkillSource.WORKSPACE]
    assert [(item.source, item.entry_name, item.code) for item in view.diagnostics] == [
        (SkillSource.USER, "<catalog>", "catalog_root_unavailable")
    ]
    assert view.usable is False
    assert catalog.resolve(()) is None
    with pytest.raises(SkillCatalogError) as captured:
        catalog.resolve(("review",))
    assert captured.value.code == "skill_catalog_unavailable"


def test_both_unavailable_roots_reject_nonempty_selection(tmp_path: Path) -> None:
    workspace_root = tmp_path / ".coding-agent" / "skills"
    workspace_root.parent.mkdir(parents=True)
    workspace_root.write_text("not a catalog", encoding="utf-8")
    catalog = SkillCatalog.from_environment(tmp_path, environ={})
    view = catalog.discover()
    assert view.skills == ()
    assert view.usable is False
    assert [item.code for item in view.diagnostics] == [
        "catalog_root_unavailable",
        "catalog_root_unavailable",
    ]
    with pytest.raises(SkillCatalogError) as captured:
        catalog.resolve(("missing",))
    assert captured.value.code == "skill_catalog_unavailable"
```

The test bodies must:

- create the target only under `tmp_path`;
- use `Path.symlink_to()` for symlink cases and fail the test if the target Windows environment cannot create the link;
- create the junction with `cmd /c mklink /J` using explicit resolved paths within `tmp_path`, then assert the command exit code is zero;
- place a unique private body in the target;
- assert no discovered descriptor or diagnostic representation contains that body or an absolute path;
- assert `catalog_root_unavailable` or `unsafe_skill_path` as appropriate;
- remove the junction using `os.rmdir()` in `finally`, never recursive deletion;
- prove `%LOCALAPPDATA%\MiniCodex\skills` is the exact production user-root construction;
- pass `environ={}` to `SkillCatalog.from_environment()`, prove a valid workspace Skill is still discoverable but the view is unusable for non-empty resolution, and assert `skill_catalog_unavailable`;
- make both production roots unavailable and assert the same stable non-empty-resolution error without exposing either path.

- [ ] **Step 10: Run filesystem-safety RED**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_skills.py -k "symlink or junction or non_directory_root or missing_localappdata" -q -p no:cacheprovider --basetemp "$env:TEMP\coding-agent-task21-pytest\task21-skill-path-red"
```

Expected: nonzero exit because reparse detection and environment construction are absent. A permanent skip is not acceptable on the target Windows environment.

- [ ] **Step 11: Implement non-following path checks and environment construction**

Use `os.lstat()` and the Windows `st_file_attributes & 0x400` reparse flag in addition to `stat.S_ISLNK()`. Check the root, immediate directory, and exact `SKILL.md` before opening. Do not call `resolve()` on an untrusted catalog entry before these checks.

`SkillCatalog.from_environment(workspace_root, environ=None)` reads a copied mapping, uses `%LOCALAPPDATA%\MiniCodex\skills` only when `LOCALAPPDATA` is non-empty and absolute, and otherwise creates an internal unavailable-user-source state that emits `catalog_root_unavailable`. It never substitutes the current directory, home directory, or workspace directory. Discovery retains safe valid descriptors from a readable source but marks the view unusable if any source is unavailable. `resolve(())` still returns `None`; every non-empty selection fails with `skill_catalog_unavailable` before duplicate or selected-ID lookup whenever global uniqueness cannot be proven.

- [ ] **Step 12: Run filesystem-safety GREEN and complete Skill tests**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_skills.py -k "symlink or junction or non_directory_root or missing_localappdata" -q -p no:cacheprovider --basetemp "$env:TEMP\coding-agent-task21-pytest\task21-skill-path-green"
.\.venv\Scripts\python.exe -m pytest tests\test_skills.py -q -p no:cacheprovider --basetemp "$env:TEMP\coding-agent-task21-pytest\task21-skills-complete"
.\.venv\Scripts\python.exe -m pytest tests\test_path_safety.py tests\tools\test_read_tools.py tests\tools\test_write_tools.py tests\tools\test_shell_tool.py -q -p no:cacheprovider --basetemp "$env:TEMP\coding-agent-task21-pytest\task21-safety-regression"
```

Expected: all commands exit `0`; Windows link and junction tests execute rather than skip; report actual counts.

---

### Task 3: Schema v2, Session Selection, and Safe Run Metadata

**Files:**
- Modify: `src/coding_agent/session_store.py`
- Modify: `tests/test_session_store.py`

**Interfaces:**
- Consumes: `SkillDescriptor`, `SkillSource`, and `RunSkillSnapshotMetadata` from Task 1.
- Produces: schema v2 and the locked `SessionStore` selection/snapshot methods.

- [ ] **Step 1: Write schema migration RED tests**

Change the existing fresh-database assertion from version 1 to version 2 and require both new tables. Add:

```python
def test_initialize_migrates_v1_sessions_to_empty_skill_selection(
    tmp_path: Path,
) -> None:
    store = SQLiteSessionStore(tmp_path, utc_clock=lambda: NOW)
    store.initialize()
    submission = store.create_session("existing")
    database = tmp_path / ".coding-agent" / "sessions.sqlite3"
    with sqlite3.connect(database) as connection:
        connection.execute("DROP TABLE IF EXISTS run_skill_snapshots")
        connection.execute("DROP TABLE IF EXISTS session_skill_selections")
        connection.execute("PRAGMA user_version = 1")
        connection.commit()
    migrated = SQLiteSessionStore(tmp_path, utc_clock=lambda: NOW)
    migrated.initialize()
    assert migrated.get_session(submission.session.session_id).title == "existing"
    assert migrated.get_skill_selection(submission.session.session_id) == ()
    assert migrated.get_run_skill_snapshots(submission.run.run_id) == ()
    with sqlite3.connect(database) as connection:
        assert connection.execute("PRAGMA user_version").fetchone() == (2,)


def test_skill_reads_distinguish_missing_parent_from_empty_children(
    tmp_path: Path,
) -> None:
    store = SQLiteSessionStore(tmp_path, utc_clock=lambda: NOW)
    store.initialize()
    with pytest.raises(SessionStoreError) as session_error:
        store.get_skill_selection("f" * 32)
    assert session_error.value.code == "session_not_found"
    with pytest.raises(SessionStoreError) as run_error:
        store.get_run_skill_snapshots("e" * 32)
    assert run_error.value.code == "run_not_found"
```

Update the existing future-schema test to write `PRAGMA user_version = 3` and still expect `schema_unsupported`.

- [ ] **Step 2: Run schema RED**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_session_store.py -k "versioned_wal or migrates_v1 or newer_version or distinguish_missing_parent" -q -p no:cacheprovider --basetemp "$env:TEMP\coding-agent-task21-pytest\task21-schema-red"
```

Expected: nonzero exit because schema version remains 1 and the new store methods and tables do not exist. The missing-parent test must fail for missing APIs, never because an absent parent is accepted as an empty selection.

- [ ] **Step 3: Add schema v2 and read methods**

Set `SCHEMA_VERSION = 2`. Add the exact two `CREATE TABLE IF NOT EXISTS` statements from the spec after `session_runs` and before events or indexes. Extend `SessionStore` Protocol with the locked methods.

Implement ordered reads with exact queries:

```sql
SELECT position, skill_id
FROM session_skill_selections
WHERE session_id = ?
ORDER BY position
```

and:

```sql
SELECT position, skill_id, source, sha256, char_count
FROM run_skill_snapshots
WHERE run_id = ?
ORDER BY position
```

Before either child query, call the existing `_select_session()` or `_select_run()` in the same connection so a missing parent retains the stable `session_not_found` or `run_not_found` error. Decode and validate every returned field, including `source` through `SkillSource`, identifier syntax, one-based contiguous positions, lowercase SHA-256, and positive character count. Translate SQLite failures and any enum/value/dataclass decoding failure through the existing safe `database_corrupt` boundary without exposing the bad value.

- [ ] **Step 4: Run schema GREEN and existing store regression**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_session_store.py -k "versioned_wal or migrates_v1 or newer_version or distinguish_missing_parent" -q -p no:cacheprovider --basetemp "$env:TEMP\coding-agent-task21-pytest\task21-schema-green"
.\.venv\Scripts\python.exe -m pytest tests\test_session_store.py -q -p no:cacheprovider --basetemp "$env:TEMP\coding-agent-task21-pytest\task21-schema-regression"
```

Expected: both exit `0`; report actual counts.

- [ ] **Step 5: Write selection replacement RED tests**

Add a helper that creates a session and calls `recover_incomplete_runs()` to return it to `IDLE`, then add:

```python
def test_replace_skill_selection_is_ordered_and_atomic(tmp_path: Path) -> None:
    store = SQLiteSessionStore(tmp_path, utc_clock=lambda: NOW)
    store.initialize()
    submission = store.create_session("first")
    store.recover_incomplete_runs()
    assert store.replace_skill_selection(
        submission.session.session_id,
        ("second", "first"),
    ) == ("second", "first")
    assert store.get_skill_selection(submission.session.session_id) == (
        "second",
        "first",
    )
    with pytest.raises(SessionStoreError) as captured:
        store.replace_skill_selection(
            submission.session.session_id,
            ("valid", "valid"),
        )
    assert captured.value.code == "invalid_skill_selection"
    assert store.get_skill_selection(submission.session.session_id) == (
        "second",
        "first",
    )
    assert store.replace_skill_selection(submission.session.session_id, ()) == ()


def test_replace_skill_selection_rejects_running_session(tmp_path: Path) -> None:
    store = SQLiteSessionStore(tmp_path, utc_clock=lambda: NOW)
    store.initialize()
    submission = store.create_session("running")
    with pytest.raises(SessionStoreError) as captured:
        store.replace_skill_selection(submission.session.session_id, ("review",))
    assert captured.value.code == "invalid_session_state"
    assert store.get_skill_selection(submission.session.session_id) == ()
```

- [ ] **Step 6: Run selection-store RED**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_session_store.py -k "replace_skill_selection" -q -p no:cacheprovider --basetemp "$env:TEMP\coding-agent-task21-pytest\task21-store-selection-red"
```

Expected: nonzero exit because replacement is absent.

- [ ] **Step 7: Implement transactional replacement**

Validate `type(skill_ids) is tuple`, every ID with the Task21 ID regex, and uniqueness before opening a transaction. Within `BEGIN IMMEDIATE`:

1. select and decode the session;
2. require `SessionStatus.IDLE` and no active workspace run;
3. delete current rows;
4. insert one-based ordered rows;
5. reread the ordered tuple;
6. commit and return it.

Any validation, integrity, or SQLite failure rolls back and preserves the old rows. Use `invalid_skill_selection`, `invalid_session_state`, and existing safe storage codes only.

- [ ] **Step 8: Run selection-store GREEN and regression**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_session_store.py -k "replace_skill_selection" -q -p no:cacheprovider --basetemp "$env:TEMP\coding-agent-task21-pytest\task21-store-selection-green"
.\.venv\Scripts\python.exe -m pytest tests\test_session_store.py tests\test_session.py -q -p no:cacheprovider --basetemp "$env:TEMP\coding-agent-task21-pytest\task21-store-selection-regression"
```

Expected: both exit `0`; report actual counts.

- [ ] **Step 9: Write RED tests for first-run and follow-up snapshot metadata**

Import `SkillDescriptor` and `SkillSource`, define a local descriptor helper, and add:

```python
def descriptor(skill_id: str, source: SkillSource) -> SkillDescriptor:
    body = f"body-{skill_id}"
    return SkillDescriptor(
        skill_id=skill_id,
        name=skill_id.title(),
        description="safe",
        source=source,
        sha256=hashlib.sha256(body.encode("utf-8")).hexdigest(),
        char_count=len(body),
    )


def test_create_and_submit_persist_safe_skill_snapshot_metadata(
    tmp_path: Path,
) -> None:
    ids = iter(("1" * 32, "2" * 32, "3" * 32))
    store = SQLiteSessionStore(tmp_path, id_factory=lambda: next(ids))
    store.initialize()
    selected = (
        descriptor("second", SkillSource.WORKSPACE),
        descriptor("first", SkillSource.USER),
    )
    first = store.create_session("first", selected_skills=selected)
    assert store.get_skill_selection(first.session.session_id) == ("second", "first")
    assert store.get_run_skill_snapshots(first.run.run_id) == tuple(
        RunSkillSnapshotMetadata(
            skill_id=item.skill_id,
            source=item.source,
            sha256=item.sha256,
            char_count=item.char_count,
        )
        for item in selected
    )
    store.recover_incomplete_runs()
    second = store.submit_message(
        first.session.session_id,
        "second",
        selected_skills=selected,
    )
    assert store.get_run_skill_snapshots(second.run.run_id) == store.get_run_skill_snapshots(first.run.run_id)


def test_submit_rejects_stale_resolved_selection_without_side_effect(
    tmp_path: Path,
) -> None:
    store = SQLiteSessionStore(tmp_path)
    store.initialize()
    first = store.create_session(
        "first",
        selected_skills=(descriptor("first", SkillSource.USER),),
    )
    store.recover_incomplete_runs()
    store.replace_skill_selection(first.session.session_id, ("second",))
    before_runs = store.list_runs(first.session.session_id)
    before_events = store.load_events(first.session.session_id)
    with pytest.raises(SessionStoreError) as captured:
        store.submit_message(
            first.session.session_id,
            "stale",
            selected_skills=(descriptor("first", SkillSource.USER),),
        )
    assert captured.value.code == "invalid_session_state"
    assert store.list_runs(first.session.session_id) == before_runs
    assert store.load_events(first.session.session_id) == before_events


@pytest.mark.parametrize(
    ("table", "assignment"),
    (
        ("session_skill_selections", "skill_id = 'Bad_ID'"),
        ("session_skill_selections", "position = 0"),
        ("run_skill_snapshots", "source = 'corrupt'"),
        ("run_skill_snapshots", "sha256 = 'not-a-hash'"),
        ("run_skill_snapshots", "char_count = 0"),
    ),
)
def test_corrupt_skill_rows_are_reported_as_database_corrupt(
    tmp_path: Path,
    table: str,
    assignment: str,
) -> None:
    store = SQLiteSessionStore(tmp_path)
    store.initialize()
    first = store.create_session(
        "first",
        selected_skills=(descriptor("first", SkillSource.USER),),
    )
    database = tmp_path / ".coding-agent" / "sessions.sqlite3"
    with sqlite3.connect(database) as connection:
        connection.execute("PRAGMA ignore_check_constraints = ON")
        connection.execute(f"UPDATE {table} SET {assignment}")
        connection.commit()
    with pytest.raises(SessionStoreError) as captured:
        if table == "session_skill_selections":
            store.get_skill_selection(first.session.session_id)
        else:
            store.get_run_skill_snapshots(first.run.run_id)
    assert captured.value.code == "database_corrupt"
    assert "Bad_ID" not in repr(captured.value)
    assert "not-a-hash" not in repr(captured.value)
```

- [ ] **Step 10: Run snapshot-store RED**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_session_store.py -k "skill_snapshot_metadata or stale_resolved_selection" -q -p no:cacheprovider --basetemp "$env:TEMP\coding-agent-task21-pytest\task21-store-snapshot-red"
```

Expected: nonzero exit because create/submit do not accept descriptor metadata or persist snapshot rows, and corrupt persisted values are not yet mapped to the stable safe error.

- [ ] **Step 11: Implement atomic selection and snapshot inserts**

Add private validation that requires `type(selected_skills) is tuple`, exact `SkillDescriptor` instances, and unique IDs. In `create_session()` insert session selection and run snapshot rows in the same existing transaction before commit. In `submit_message()` reread selection inside the transaction and compare its ordered IDs with the descriptor tuple before inserting the run and snapshots.

Insert only `skill_id`, `source.value`, `sha256`, and `char_count` into run rows. Do not serialize a descriptor, name, description, body, or path as JSON.

- [ ] **Step 12: Run snapshot-store GREEN, privacy query, and regression**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_session_store.py -k "skill_snapshot_metadata or stale_resolved_selection" -q -p no:cacheprovider --basetemp "$env:TEMP\coding-agent-task21-pytest\task21-store-snapshot-green"
.\.venv\Scripts\python.exe -m pytest tests\test_session_store.py tests\test_session.py -q -p no:cacheprovider --basetemp "$env:TEMP\coding-agent-task21-pytest\task21-store-complete"
.\.venv\Scripts\python.exe -c "from pathlib import Path; import sqlite3,tempfile; from coding_agent.session_store import SQLiteSessionStore; from coding_agent.skills import SkillDescriptor,SkillSource; import hashlib; root=Path(tempfile.mkdtemp()); store=SQLiteSessionStore(root); store.initialize(); body='task21-private-instruction-sentinel'; item=SkillDescriptor('review','Review','safe',SkillSource.USER,hashlib.sha256(body.encode()).hexdigest(),len(body)); store.create_session('safe message',selected_skills=(item,)); dump='\n'.join(sqlite3.connect(root/'.coding-agent'/'sessions.sqlite3').iterdump()); assert body not in dump; assert 'Review' not in dump; print('skill body absent from SQLite')"
```

Expected: all commands exit `0`; the privacy command prints only `skill body absent from SQLite`; report actual test counts.

---

### Task 3A: Frozen Runtime Request Carrier Prerequisite

This approved ordering amendment must complete before Task 4 because the
controller GREEN path constructs `SessionRunRequest(skill_bundle=...)`.

**Files:**
- Modify: `src/coding_agent/session_runtime.py`
- Modify: `tests/test_session_runtime.py`

- [ ] **Step 1: Write request invariant and hidden-repr RED test**

In `tests/test_session_runtime.py`, add a local helper that writes one valid
restricted `SKILL.md` under `tmp_path`, resolve it through `SkillCatalog`, and
add:

```python
def test_session_run_request_accepts_frozen_skill_bundle_and_hides_body(
    tmp_path: Path,
) -> None:
    root = tmp_path / "skills"
    write_skill(root, "review", "task21 private runtime body")
    bundle = SkillCatalog(
        user_root=root,
        workspace_root=tmp_path / "workspace",
    ).resolve(("review",))
    assert bundle is not None
    request = SessionRunRequest(
        session_id="1" * 32,
        run_id="2" * 32,
        current_message="inspect",
        initial_user_message="inspect",
        skill_bundle=bundle,
    )
    assert request.skill_bundle is bundle
    assert "task21 private runtime body" not in repr(request)
    with pytest.raises(TypeError):
        SessionRunRequest(
            session_id="1" * 32,
            run_id="2" * 32,
            current_message="inspect",
            initial_user_message="inspect",
            skill_bundle="invalid",  # type: ignore[arg-type]
        )
```

- [ ] **Step 2: Run request RED**

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_session_runtime.py::test_session_run_request_accepts_frozen_skill_bundle_and_hides_body -q -p no:cacheprovider --basetemp "$env:TEMP\coding-agent-task21-pytest\task21-runtime-request-red"
```

Expected: nonzero exit because `SessionRunRequest` lacks the field.

- [ ] **Step 3: Add the frozen optional request field**

Import and add the exact `skill_bundle: SkillInstructionBundle | None =
field(default=None, repr=False)` field after existing required fields. In
`__post_init__`, require `None` or an exact `SkillInstructionBundle`; invalid
values raise `TypeError`. Existing construction without the keyword remains
unchanged. Do not expose the bundle through narrative, event, outcome, result,
or report records.

- [ ] **Step 4: Run request GREEN and runtime regression**

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_session_runtime.py::test_session_run_request_accepts_frozen_skill_bundle_and_hides_body -q -p no:cacheprovider --basetemp "$env:TEMP\coding-agent-task21-pytest\task21-runtime-request-green"
.\.venv\Scripts\python.exe -m pytest tests\test_session_runtime.py tests\test_session.py -q -p no:cacheprovider --basetemp "$env:TEMP\coding-agent-task21-pytest\task21-runtime-request-regression"
```

Expected: both commands exit `0`; report actual counts.

---

### Task 4: Controller Catalog API and Selection Lifecycle

**Files:**
- Modify: `src/coding_agent/session_controller.py`
- Modify: `tests/test_session_controller.py`

**Interfaces:**
- Consumes: Task 2 `SkillCatalog`, Task 3 store methods, existing controller admission and worker lifecycle.
- Produces: `list_skills`, `get_session_skills`, `set_session_skills`, and first-run `skill_ids`.

- [ ] **Step 1: Update the controller fixture and write first-run RED**

Add a local `write_skill()` equivalent to the complete helper in `tests/test_skills.py`. Update `make_controller()` with this exact additional keyword and selection logic:

```python
def make_controller(
    tmp_path: Path,
    executor: object,
    *,
    store: SQLiteSessionStore | None = None,
    thread_factory: object | None = None,
    skill_catalog: SkillCatalog | None = None,
) -> SessionController:
    lease = WorkspaceSessionLease.acquire(tmp_path)
    selected_store = store or SQLiteSessionStore(tmp_path)
    selected_store.initialize()
    selected_store.recover_incomplete_runs()
    selected_catalog = skill_catalog or SkillCatalog(
        user_root=tmp_path / "user-skills",
        workspace_root=tmp_path / ".coding-agent" / "skills",
    )
    kwargs: dict[str, object] = {}
    if thread_factory is not None:
        kwargs["thread_factory"] = thread_factory
    return SessionController(
        store=selected_store,
        lease=lease,
        executor=executor,  # type: ignore[arg-type]
        event_hub=SessionEventHub(),
        skill_catalog=selected_catalog,
        **kwargs,  # type: ignore[arg-type]
    )
```

This keeps every controller test isolated from the developer's real user catalog.

Before the RED run, update the two existing blocking store test doubles so their
overrides remain signature-compatible with the additive store keywords:

```python
def create_session(
    self,
    message: str,
    *,
    selected_skills: tuple[SkillDescriptor, ...] = (),
):
    self.create_entered.set()
    assert self.release_create.wait(timeout=2.0)
    return super().create_session(message, selected_skills=selected_skills)

def submit_message(
    self,
    session_id: str,
    message: str,
    *,
    selected_skills: tuple[SkillDescriptor, ...] = (),
):
    self.submit_entered.set()
    assert self.release_submit.wait(timeout=2.0)
    return super().submit_message(
        session_id,
        message,
        selected_skills=selected_skills,
    )
```

This is a test-double compatibility update, not a production dual-call fallback.

Add:

```python
def test_create_session_resolves_and_persists_ordered_first_run_skills(
    tmp_path: Path,
) -> None:
    user_root = tmp_path / "user-skills"
    workspace_root = tmp_path / ".coding-agent" / "skills"
    write_skill(user_root, "first", "first private body")
    write_skill(workspace_root, "second", "second private body")
    catalog = SkillCatalog(user_root=user_root, workspace_root=workspace_root)
    executor = BlockingExecutor(tmp_path, (failed_outcome(),))
    controller = make_controller(tmp_path, executor, skill_catalog=catalog)
    handle = controller.create_session("inspect", skill_ids=("second", "first"))
    assert executor.started.wait(timeout=1.0)
    request = executor.requests[0]
    assert isinstance(request, SessionRunRequest)
    assert request.skill_bundle is not None
    assert [item.descriptor.skill_id for item in request.skill_bundle.items] == [
        "second",
        "first",
    ]
    assert controller.get_session_skills(handle.session_id) == ("second", "first")
    executor.release.set()
    controller.wait_for_run(handle.run_id, timeout_seconds=2.0)
    assert controller.shutdown(timeout_seconds=1.0) is True


def test_controller_rejects_catalog_for_different_workspace(
    tmp_path: Path,
) -> None:
    other = tmp_path / "other"
    other.mkdir()
    lease = WorkspaceSessionLease.acquire(tmp_path)
    store = SQLiteSessionStore(tmp_path)
    store.initialize()
    executor = BlockingExecutor(tmp_path, (failed_outcome(),))
    catalog = SkillCatalog(
        user_root=tmp_path / "user-skills",
        workspace_root=other / ".coding-agent" / "skills",
    )
    try:
        with pytest.raises(SessionControllerError) as captured:
            SessionController(
                store=store,
                lease=lease,
                executor=executor,
                event_hub=SessionEventHub(),
                skill_catalog=catalog,
            )
        assert captured.value.code == "invalid_session_state"
    finally:
        lease.close()
```

- [ ] **Step 2: Run first-run controller RED**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_session_controller.py::test_create_session_resolves_and_persists_ordered_first_run_skills tests\test_session_controller.py::test_controller_rejects_catalog_for_different_workspace -q -p no:cacheprovider --basetemp "$env:TEMP\coding-agent-task21-pytest\task21-controller-create-red"
```

Expected: nonzero exit because the controller lacks the catalog dependency, keyword, and query method.

- [ ] **Step 3: Add catalog dependency and first-run admission**

Add optional keyword-only `skill_catalog` to `__init__()` and `open()`. The exact expected workspace catalog path is `(store.workspace / ".coding-agent" / "skills").resolve(strict=False)`. Require the injected catalog's already-normalized `workspace_root` to equal that path; mismatch raises `SessionControllerError("invalid_session_state")` before recovery or mutation. When absent, use `SkillCatalog.from_environment(store.workspace)`.

For `create_session()`:

1. validate/render the message using existing behavior;
2. reserve admission;
3. call `resolve(skill_ids)`;
4. pass ordered descriptors through the `selected_skills` keyword to `store.create_session()`;
5. place the full bundle on `SessionRunRequest`;
6. start the worker through the existing path;
7. translate `SkillCatalogError` to `SessionControllerError` without chaining content.

Do not scan a catalog for `skill_ids=()`.

- [ ] **Step 4: Run first-run GREEN and controller regression**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_session_controller.py::test_create_session_resolves_and_persists_ordered_first_run_skills tests\test_session_controller.py::test_controller_rejects_catalog_for_different_workspace -q -p no:cacheprovider --basetemp "$env:TEMP\coding-agent-task21-pytest\task21-controller-create-green"
.\.venv\Scripts\python.exe -m pytest tests\test_session_controller.py -q -p no:cacheprovider --basetemp "$env:TEMP\coding-agent-task21-pytest\task21-controller-create-regression"
```

Expected: both exit `0`; existing calls without `skill_ids` remain green.

- [ ] **Step 5: Write idle selection and catalog query RED tests**

Add:

```python
def test_idle_session_selection_can_be_reordered_and_cleared(
    tmp_path: Path,
) -> None:
    root = tmp_path / "user-skills"
    write_skill(root, "first", "first")
    write_skill(root, "second", "second")
    catalog = SkillCatalog(user_root=root, workspace_root=tmp_path / ".coding-agent" / "skills")
    executor = BlockingExecutor(tmp_path, (failed_outcome(), failed_outcome()))
    controller = make_controller(tmp_path, executor, skill_catalog=catalog)
    first = controller.create_session("first")
    assert executor.started.wait(timeout=1.0)
    executor.release.set()
    controller.wait_for_run(first.run_id, timeout_seconds=2.0)
    assert [item.skill_id for item in controller.list_skills().skills] == ["first", "second"]
    assert controller.set_session_skills(first.session_id, ("second", "first")) == ("second", "first")
    assert controller.get_session_skills(first.session_id) == ("second", "first")
    assert controller.set_session_skills(first.session_id, ()) == ()
    assert controller.shutdown(timeout_seconds=1.0) is True


def test_selection_change_is_rejected_while_any_run_is_active(
    tmp_path: Path,
) -> None:
    root = tmp_path / "user-skills"
    write_skill(root, "review", "review")
    catalog = SkillCatalog(user_root=root, workspace_root=tmp_path / ".coding-agent" / "skills")
    executor = BlockingExecutor(tmp_path, (failed_outcome(),))
    controller = make_controller(tmp_path, executor, skill_catalog=catalog)
    handle = controller.create_session("running")
    assert executor.started.wait(timeout=1.0)
    with pytest.raises(SessionControllerError) as captured:
        controller.set_session_skills(handle.session_id, ("review",))
    assert captured.value.code == "controller_busy"
    assert controller.get_session_skills(handle.session_id) == ()
    executor.release.set()
    controller.wait_for_run(handle.run_id, timeout_seconds=2.0)
    assert controller.shutdown(timeout_seconds=1.0) is True
```

- [ ] **Step 6: Run selection-controller RED**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_session_controller.py -k "selection_can_be_reordered or selection_change_is_rejected" -q -p no:cacheprovider --basetemp "$env:TEMP\coding-agent-task21-pytest\task21-controller-selection-red"
```

Expected: nonzero exit because query and replacement methods are absent.

- [ ] **Step 7: Implement read APIs and admission-protected replacement**

`list_skills()` calls `discover()` and returns the immutable view. `get_session_skills()` translates store errors. `set_session_skills()`:

1. reserves admission using the existing lock and availability priority;
2. loads the session and requires `IDLE` before catalog resolution;
3. resolves the complete ordered tuple;
4. passes only ordered IDs to `replace_skill_selection()`;
5. releases admission in `finally`;
6. propagates `KeyboardInterrupt` and `SystemExit`;
7. leaves the old selection unchanged on ordinary failure.

- [ ] **Step 8: Run selection-controller GREEN and regression**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_session_controller.py -k "selection_can_be_reordered or selection_change_is_rejected" -q -p no:cacheprovider --basetemp "$env:TEMP\coding-agent-task21-pytest\task21-controller-selection-green"
.\.venv\Scripts\python.exe -m pytest tests\test_session_controller.py tests\test_session_store.py -q -p no:cacheprovider --basetemp "$env:TEMP\coding-agent-task21-pytest\task21-controller-selection-regression"
```

Expected: both exit `0`; report actual counts.

- [ ] **Step 9: Write follow-up, failure-atomicity, and immutable-run RED tests**

Add these exact tests, using the updated local `write_skill()` helper and injected `SkillCatalog`:

```python
def test_submit_message_resolves_persisted_selection_for_new_run(
    tmp_path: Path,
) -> None:
    root = tmp_path / "user-skills"
    write_skill(root, "review", "follow-up private body")
    catalog = SkillCatalog(
        user_root=root,
        workspace_root=tmp_path / ".coding-agent" / "skills",
    )
    executor = BlockingExecutor(tmp_path, (failed_outcome(), failed_outcome()))
    store = SQLiteSessionStore(tmp_path)
    controller = make_controller(
        tmp_path,
        executor,
        store=store,
        skill_catalog=catalog,
    )
    first = controller.create_session("first")
    assert executor.started.wait(timeout=1.0)
    executor.release.set()
    controller.wait_for_run(first.run_id, timeout_seconds=2.0)
    assert controller.set_session_skills(first.session_id, ("review",)) == ("review",)
    executor.started.clear()
    executor.release.clear()
    second = controller.submit_message(first.session_id, "second")
    assert executor.started.wait(timeout=1.0)
    request = executor.requests[-1]
    assert isinstance(request, SessionRunRequest)
    assert request.skill_bundle is not None
    assert request.skill_bundle.text.endswith("follow-up private body")
    snapshots = store.get_run_skill_snapshots(second.run_id)
    assert [item.skill_id for item in snapshots] == ["review"]
    executor.release.set()
    controller.wait_for_run(second.run_id, timeout_seconds=2.0)
    assert controller.shutdown(timeout_seconds=1.0) is True


def test_missing_selected_skill_creates_no_follow_up_run_or_event(
    tmp_path: Path,
) -> None:
    root = tmp_path / "user-skills"
    skill_file = write_skill(root, "review", "private removed body")
    catalog = SkillCatalog(
        user_root=root,
        workspace_root=tmp_path / ".coding-agent" / "skills",
    )
    executor = BlockingExecutor(tmp_path, (failed_outcome(),))
    controller = make_controller(tmp_path, executor, skill_catalog=catalog)
    first = controller.create_session("first")
    assert executor.started.wait(timeout=1.0)
    executor.release.set()
    controller.wait_for_run(first.run_id, timeout_seconds=2.0)
    controller.set_session_skills(first.session_id, ("review",))
    before = controller.get_session(first.session_id)
    skill_file.unlink()
    with pytest.raises(SessionControllerError) as captured:
        controller.submit_message(first.session_id, "second")
    assert captured.value.code == "selected_skill_unavailable"
    after = controller.get_session(first.session_id)
    assert after.runs == before.runs
    assert after.events == before.events
    assert len(executor.requests) == 1
    assert "private removed body" not in repr(captured.value)
    assert str(tmp_path) not in repr(captured.value)
    assert controller.shutdown(timeout_seconds=1.0) is True


def test_catalog_change_after_admission_does_not_change_active_bundle(
    tmp_path: Path,
) -> None:
    root = tmp_path / "user-skills"
    skill_file = write_skill(root, "review", "old private body")
    catalog = SkillCatalog(
        user_root=root,
        workspace_root=tmp_path / ".coding-agent" / "skills",
    )
    executor = BlockingExecutor(tmp_path, (failed_outcome(),))
    controller = make_controller(tmp_path, executor, skill_catalog=catalog)
    handle = controller.create_session("first", skill_ids=("review",))
    assert executor.started.wait(timeout=1.0)
    request = executor.requests[0]
    assert isinstance(request, SessionRunRequest)
    assert request.skill_bundle is not None
    write_skill(root, "review", "new private body")
    assert "old private body" in request.skill_bundle.text
    assert "new private body" not in request.skill_bundle.text
    assert skill_file.read_text(encoding="utf-8").endswith("new private body")
    executor.release.set()
    controller.wait_for_run(handle.run_id, timeout_seconds=2.0)
    assert controller.shutdown(timeout_seconds=1.0) is True


def test_skill_resolution_failure_creates_no_first_session_or_worker(
    tmp_path: Path,
) -> None:
    catalog = SkillCatalog(
        user_root=tmp_path / "user-skills",
        workspace_root=tmp_path / ".coding-agent" / "skills",
    )
    executor = BlockingExecutor(tmp_path, (failed_outcome(),))
    controller = make_controller(tmp_path, executor, skill_catalog=catalog)
    with pytest.raises(SessionControllerError) as captured:
        controller.create_session("first", skill_ids=("missing",))
    assert captured.value.code == "selected_skill_unavailable"
    assert controller.list_sessions() == ()
    assert executor.requests == []
    assert executor.started.is_set() is False
    assert str(tmp_path) not in repr(captured.value)
    assert controller.shutdown(timeout_seconds=1.0) is True
```

- [ ] **Step 10: Run lifecycle RED**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_session_controller.py -k "persisted_selection_for_new_run or missing_selected_skill or catalog_change_after_admission or resolution_failure_creates_no_first" -q -p no:cacheprovider --basetemp "$env:TEMP\coding-agent-task21-pytest\task21-controller-lifecycle-red"
```

Expected: nonzero exit because `submit_message()` does not yet resolve and attach the stored selection or enforce zero-side-effect failure.

- [ ] **Step 11: Implement follow-up resolution before store mutation**

Within existing `submit_message()` admission:

1. load narrative as before;
2. render the deterministic initial message as before;
3. load the ordered selection;
4. resolve the bundle once;
5. call `store.submit_message()` with descriptors passed through its `selected_skills` keyword;
6. build the request with that exact bundle;
7. start the worker.

Do not reread Skill bodies in the worker. Preserve existing store selection comparison to detect a concurrent mismatch. Every resolution failure happens before the store creates the follow-up run and events.

- [ ] **Step 12: Run lifecycle GREEN and complete controller regression**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_session_controller.py -k "persisted_selection_for_new_run or missing_selected_skill or catalog_change_after_admission or resolution_failure_creates_no_first" -q -p no:cacheprovider --basetemp "$env:TEMP\coding-agent-task21-pytest\task21-controller-lifecycle-green"
.\.venv\Scripts\python.exe -m pytest tests\test_session_controller.py tests\test_session_store.py tests\test_session_events.py -q -p no:cacheprovider --basetemp "$env:TEMP\coding-agent-task21-pytest\task21-controller-complete"
```

Expected: both exit `0`; record actual counts, warnings, and skips.

---

### Task 5: Application and Executor Instruction Integration

**Files:**
- Modify: `src/coding_agent/session_runtime.py`
- Modify: `src/coding_agent/app.py`
- Modify: `tests/test_session_runtime.py`
- Modify: `tests/test_app.py`

**Interfaces:**
- Consumes: the Task 3A frozen `SkillInstructionBundle` carrier and the existing `RunInstructionBuilder.build(workspace, *, skill_instructions=None)`.
- Produces: one-way propagation into the main model request without changing Agent, context-summary, tool, or provider interfaces.

- [ ] **Step 1: Write application instruction propagation RED tests**

In `tests/test_app.py`, create factories around one named `FakeModelClient` and add:

```python
def _factories_with_model_client(
    workspace: Path,
    client: FakeModelClient,
    *,
    run_id: str,
) -> ApplicationFactories:
    executor = RecordingExecutor()

    def logger_factory(config: RunConfig, clock: object) -> RunEventLogger:
        assert config.workspace == workspace.resolve(strict=True)
        return RunEventLogger.create(
            config.workspace,
            run_id=run_id,
            sensitive_values=(config.api_key,),
            monotonic_clock=clock,  # type: ignore[arg-type]
        )

    return ApplicationFactories(
        model_client=lambda config: client,
        logger=logger_factory,
        command_executor=lambda: executor,  # type: ignore[arg-type]
        clock=lambda: 0.0,
    )


def test_execute_agent_run_includes_selected_skill_in_main_request_only(
    tmp_path: Path,
) -> None:
    client = FakeModelClient((ModelResponse(text="done"),))
    factories = _factories_with_model_client(
        tmp_path,
        client,
        run_id="6" * 32,
    )
    private_body = "private selected instructions"
    result = execute_agent_run(
        _config(tmp_path),
        factories=factories,
        skill_instructions=f"### Skill: review — Review\n{private_body}",
    )
    assert result.report.status.value == "success"
    assert client.requests
    instructions = client.requests[0].instructions
    assert instructions is not None
    assert "## Selected skill instructions" in instructions
    assert private_body in instructions
    assert private_body not in json.dumps(result.report.to_dict(), ensure_ascii=False)
    assert private_body not in (tmp_path / result.report.log_path).read_text(
        encoding="utf-8"
    )


def test_execute_agent_run_without_skills_preserves_existing_instructions(
    tmp_path: Path,
) -> None:
    first_client = FakeModelClient((ModelResponse(text="done"),))
    second_client = FakeModelClient((ModelResponse(text="done"),))
    execute_agent_run(
        _config(tmp_path),
        factories=_factories_with_model_client(
            tmp_path,
            first_client,
            run_id="7" * 32,
        ),
    )
    execute_agent_run(
        _config(tmp_path),
        factories=_factories_with_model_client(
            tmp_path,
            second_client,
            run_id="8" * 32,
        ),
        skill_instructions=None,
    )
    assert first_client.requests[0].instructions == second_client.requests[0].instructions
    assert "## Selected skill instructions" not in first_client.requests[0].instructions
```

- [ ] **Step 2: Run application RED**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_app.py -k "selected_skill_in_main_request_only or without_skills_preserves" -q -p no:cacheprovider --basetemp "$env:TEMP\coding-agent-task21-pytest\task21-app-instructions-red"
```

Expected: nonzero exit because `execute_agent_run()` does not accept or forward the additive keyword.

- [ ] **Step 3: Add the single instruction-builder connection**

Add `skill_instructions: str | None = None` to `execute_agent_run()` after existing optional event/callback keywords. Replace:

```python
RunInstructionBuilder().build(config.workspace)
```

with:

```python
RunInstructionBuilder().build(
    config.workspace,
    skill_instructions=skill_instructions,
)
```

Do not modify `RunInstructionBuilder`, `AgentRunner`, `ContextManager`, providers, tools, or logging.

- [ ] **Step 4: Run application GREEN and app/instruction regression**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_app.py -k "selected_skill_in_main_request_only or without_skills_preserves" -q -p no:cacheprovider --basetemp "$env:TEMP\coding-agent-task21-pytest\task21-app-instructions-green"
.\.venv\Scripts\python.exe -m pytest tests\test_app.py tests\test_instructions.py tests\test_context.py tests\test_agent_loop.py -q -p no:cacheprovider --basetemp "$env:TEMP\coding-agent-task21-pytest\task21-app-instructions-regression"
```

Expected: both exit `0`; report actual counts.

- [ ] **Step 5: Write executor propagation RED test**

In `tests/test_session_runtime.py`, adapt the existing successful executor test to use a named `FakeModelClient` and add a second test that passes a real bundle on `SessionRunRequest`. After execution, assert:

```python
assert client.requests
assert client.requests[0].instructions is not None
assert "task21 private runtime body" in client.requests[0].instructions
assert "task21 private runtime body" not in json.dumps(
    outcome.safe_summary,
    ensure_ascii=False,
)
assert "task21 private runtime body" not in json.dumps(
    outcome.final_report,
    ensure_ascii=False,
)
```

Name the test `test_agent_session_executor_passes_skill_bundle_without_persisting_body`.

- [ ] **Step 6: Run executor propagation RED**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_session_runtime.py::test_agent_session_executor_passes_skill_bundle_without_persisting_body -q -p no:cacheprovider --basetemp "$env:TEMP\coding-agent-task21-pytest\task21-runtime-executor-red"
```

Expected: nonzero exit because `AgentSessionRunExecutor.execute()` does not forward bundle text.

- [ ] **Step 7: Forward only the immutable combined text**

In `AgentSessionRunExecutor.execute()`, compute:

```python
skill_instructions = (
    None if request.skill_bundle is None else request.skill_bundle.text
)
```

and pass it to `execute_agent_run()`. Do not place the bundle or text in `SessionRunOutcome`, safe summaries, reports, or events.

- [ ] **Step 8: Run executor GREEN and complete integration regression**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_session_runtime.py::test_agent_session_executor_passes_skill_bundle_without_persisting_body -q -p no:cacheprovider --basetemp "$env:TEMP\coding-agent-task21-pytest\task21-runtime-executor-green"
.\.venv\Scripts\python.exe -m pytest tests\test_skills.py tests\test_session_store.py tests\test_session_runtime.py tests\test_session_controller.py tests\test_app.py tests\test_instructions.py tests\test_context.py tests\test_agent_loop.py -q -p no:cacheprovider --basetemp "$env:TEMP\coding-agent-task21-pytest\task21-integration-complete"
```

Expected: both exit `0`; main requests contain the selected Skill text, summary requests retain existing `instructions=None`, and no persisted or reported structure contains the body.

---

### Task 6: Offline Boundary and Final Verification

**Files:**
- Test: all Task21 and repository tests
- Inspect: every changed file and the complete Git diff
- Modify: none unless a verification failure is first diagnosed through `superpowers:systematic-debugging` and the fix remains inside the locked map

**Interfaces:**
- Consumes: complete Task21 behavior.
- Produces: fresh evidence for the Task21 acceptance checkpoint; no commit and no Task22 work.

- [ ] **Step 1: Add and run the offline import boundary test**

Add this test to `tests/test_skills.py` before the final run:

```python
def test_skill_and_session_modules_import_without_provider_or_network(
    tmp_path: Path,
) -> None:
    script = """
import builtins
import importlib
import os
import socket

for name in ("OPENAI_API_KEY", "CHAT_COMPLETIONS_API_KEY"):
    os.environ.pop(name, None)
forbidden = {"openai", "httpx", "requests"}
real_import = builtins.__import__

def guarded_import(name, *args, **kwargs):
    if name.split(".")[0] in forbidden:
        raise AssertionError(name)
    return real_import(name, *args, **kwargs)

builtins.__import__ = guarded_import
socket.socket = lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("network"))
for name in (
    "coding_agent.skills",
    "coding_agent.session",
    "coding_agent.session_store",
    "coding_agent.session_runtime",
    "coding_agent.session_controller",
):
    importlib.import_module(name)
"""
    completed = subprocess.run(
        [sys.executable, "-c", script],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
```

Add `subprocess` and `sys` imports at the top of `tests/test_skills.py`.

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_skills.py::test_skill_and_session_modules_import_without_provider_or_network -q -p no:cacheprovider --basetemp "$env:TEMP\coding-agent-task21-pytest\task21-offline"
```

Expected: exit `0`; no provider package import and no socket construction occurs.

- [ ] **Step 2: Run every Task21 focused suite**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_skills.py -q -p no:cacheprovider --basetemp "$env:TEMP\coding-agent-task21-pytest\task21-final-skills"
.\.venv\Scripts\python.exe -m pytest tests\test_session_store.py -q -p no:cacheprovider --basetemp "$env:TEMP\coding-agent-task21-pytest\task21-final-store"
.\.venv\Scripts\python.exe -m pytest tests\test_session_controller.py -q -p no:cacheprovider --basetemp "$env:TEMP\coding-agent-task21-pytest\task21-final-controller"
.\.venv\Scripts\python.exe -m pytest tests\test_session_runtime.py tests\test_app.py tests\test_instructions.py -q -p no:cacheprovider --basetemp "$env:TEMP\coding-agent-task21-pytest\task21-final-integration"
```

Expected: every command exits `0`; report actual pass, fail, skip, warning, and duration output separately.

- [ ] **Step 3: Run Windows path/reparse and existing safety regressions**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_skills.py -k "symlink or junction or reparse" -q -p no:cacheprovider --basetemp "$env:TEMP\coding-agent-task21-pytest\task21-final-reparse"
.\.venv\Scripts\python.exe -m pytest tests\test_path_safety.py tests\tools\test_read_tools.py tests\tools\test_write_tools.py tests\tools\test_shell_tool.py -q -p no:cacheprovider --basetemp "$env:TEMP\coding-agent-task21-pytest\task21-final-safety"
```

Expected: both exit `0`; Windows Skill symlink/junction/reparse tests are collected and executed with zero skip; Task8 safety tests remain green.

- [ ] **Step 4: Run explicit Task1–Task20 component regression**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_cli.py tests\test_messages.py tests\test_model.py tests\test_agent_loop.py tests\test_context.py tests\test_termination.py tests\test_verification.py tests\test_streaming.py tests\test_logging.py tests\test_report.py tests\test_openai_client.py tests\test_chat_completions_client.py tests\test_session.py tests\test_session_store.py tests\test_session_events.py tests\test_session_runtime.py tests\test_session_controller.py tests\integration -q -p no:cacheprovider --basetemp "$env:TEMP\coding-agent-task21-pytest\task21-final-components"
```

Expected: exit `0`; record actual counts. No existing accepted behavior is weakened.

- [ ] **Step 5: Run the complete repository suite**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider --basetemp "$env:TEMP\coding-agent-task21-pytest\task21-final-all"
```

Expected: exit `0`; record fresh pass, fail, skip, warning, and duration output. Do not reuse an earlier count.

- [ ] **Step 6: Verify public signatures and provider-neutral boundaries**

Run:

```powershell
.\.venv\Scripts\python.exe -c "import inspect; from coding_agent.skills import SkillCatalog; from coding_agent.session_controller import SessionController; from coding_agent.session_runtime import SessionRunRequest; from coding_agent.app import execute_agent_run; from coding_agent.model import ModelClient; print(inspect.signature(SkillCatalog)); print(inspect.signature(SkillCatalog.discover)); print(inspect.signature(SkillCatalog.resolve)); print(inspect.signature(SessionController.create_session)); print(inspect.signature(SessionController.submit_message)); print(inspect.signature(SessionController.set_session_skills)); print(inspect.signature(execute_agent_run)); print(inspect.signature(ModelClient.complete)); print(SessionRunRequest.__dataclass_fields__['skill_bundle'].repr)"
.\.venv\Scripts\python.exe -c "import ast,pathlib; files=sorted(pathlib.Path('src').rglob('*.py'))+sorted(pathlib.Path('tests').rglob('*.py')); [ast.parse(p.read_text(encoding='utf-8'), filename=str(p)) for p in files]; print(f'AST parsed {len(files)} Python files')"
rg -n "from openai|import openai|httpx|requests" src\coding_agent\skills.py src\coding_agent\session_store.py src\coding_agent\session_runtime.py src\coding_agent\session_controller.py
rg -n "RunInstructionBuilder|skill_instructions" src\coding_agent\app.py src\coding_agent\session_runtime.py
git diff --exit-code -- src\coding_agent\context.py
.\.venv\Scripts\python.exe -c "from coding_agent.messages import ModelRequest; assert ModelRequest.__dataclass_fields__['instructions'].default is None; print('summary instructions default: None')"
```

Expected: signatures match the locked plan; `ModelClient.complete` is unchanged; `skill_bundle` has `repr=False`; AST parsing exits `0`; provider-import scan has no match in Skill/session modules; Skill text has exactly one route through the existing instruction builder; `context.py` remains unchanged and summary instructions retain the existing `None` default.

- [ ] **Step 7: Inspect schema, ordering, and absence of bodies**

Run:

```powershell
.\.venv\Scripts\python.exe -c "from pathlib import Path; import sqlite3,tempfile; from coding_agent.session_store import SQLiteSessionStore; root=Path(tempfile.mkdtemp()); store=SQLiteSessionStore(root); store.initialize(); db=root/'.coding-agent'/'sessions.sqlite3'; c=sqlite3.connect(db); print(c.execute('PRAGMA user_version').fetchone()[0]); print([r[0] for r in c.execute(\"SELECT name FROM sqlite_master WHERE type='table' ORDER BY name\")]); c.close()"
rg -n "session_skill_selections|run_skill_snapshots|ORDER BY position|BEGIN IMMEDIATE" src\coding_agent\session_store.py
rg -n "instructions|body|text|path|name|description" src\coding_agent\session_store.py
```

Expected: schema version is `2`; both tables exist; ordered reads and transactional replacement are present. Every sensitive-term match in the store is manually classified as existing session/report handling or a negative validation assertion; no Skill body column or serialization exists.

- [ ] **Step 8: Audit deterministic authority and deferred scope**

Run:

```powershell
git diff -- src\coding_agent\agent.py src\coding_agent\state.py src\coding_agent\safety.py src\coding_agent\verification.py src\coding_agent\termination.py src\coding_agent\tools src\coding_agent\model.py src\coding_agent\openai_client.py src\coding_agent\chat_completions_client.py src\coding_agent\cli.py src\coding_agent\config.py pyproject.toml
rg -n "exec\(|eval\(|compile\(|importlib|subprocess|socket|urllib|http://|https://|MCP|marketplace|plugin" src\coding_agent\skills.py
rg -n "LangChain|LlamaIndex|Agents SDK|Claude Agent SDK|AutoGen|CrewAI|FastAPI|Starlette|Flask|Django|aiohttp|websocket" src tests pyproject.toml
```

Expected: protected-module and dependency diff is empty; `skills.py` contains no execution, import loading, process, socket, URL, MCP, marketplace, or plugin capability; no prohibited Agent/web framework is introduced. Test-only negative assertions are manually classified.

- [ ] **Step 9: Scan credentials, paths, unfinished markers, and test suppression**

Run:

```powershell
$changed = git diff --name-only --diff-filter=ACMRT
$changed += git ls-files --others --exclude-standard
$changed = $changed | Sort-Object -Unique
$files = $changed | Where-Object { Test-Path $_ } | ForEach-Object { Get-Item $_ }
$credentials = $files | Select-String -Pattern 'sk-[A-Za-z0-9_-]{16,}|Bearer\s+[A-Za-z0-9._-]{12,}|OPENAI_API_KEY\s*=\s*["''][^<][^"'']{8,}'
if ($credentials) { $credentials | Select-Object Path,LineNumber; throw 'credential-like content found' }
$personalPattern = '[A-Za-z]:\\' + 'Users\\' + '|' + '/' + 'home/' + '[^/]+/'
$personal = $files | Select-String -Pattern $personalPattern
if ($personal) { $personal | Select-Object Path,LineNumber; throw 'personal absolute path found' }
$unfinishedPattern = 'TO[D]O|TB[D]|FIX[M]E|NotImplemented' + 'Error'
rg -n $unfinishedPattern src\coding_agent\skills.py src\coding_agent\session_store.py src\coding_agent\session_runtime.py src\coding_agent\session_controller.py src\coding_agent\app.py tests\test_skills.py tests\test_session_store.py tests\test_session_runtime.py tests\test_session_controller.py tests\test_app.py
rg -n "pytest\.skip|pytest\.xfail|@pytest\.mark\.(skip|xfail)" tests\test_skills.py tests\test_session_store.py tests\test_session_runtime.py tests\test_session_controller.py tests\test_app.py
```

Expected: no real credential or newly introduced personal absolute path; no unfinished implementation marker; no skip/xfail. Do not print a suspected secret value.

- [ ] **Step 10: Check dependency health, whitespace, status, and complete diff**

Run:

```powershell
.\.venv\Scripts\python.exe -m pip check
git diff --check
git status --short --untracked-files=all
git diff --stat
git diff -- src\coding_agent\skills.py src\coding_agent\session_store.py src\coding_agent\session_runtime.py src\coding_agent\session_controller.py src\coding_agent\app.py tests\test_skills.py tests\test_session_store.py tests\test_session_runtime.py tests\test_session_controller.py tests\test_app.py TASKS.md
$newFiles = @(
    'src\coding_agent\skills.py',
    'tests\test_skills.py'
)
foreach ($path in $newFiles) {
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
        throw "missing new file: $path"
    }
    "===== UNTRACKED FILE: $path ====="
    Get-Content -Raw -LiteralPath $path
    $text = [System.IO.File]::ReadAllText((Resolve-Path -LiteralPath $path))
    if ($text -match '(?m)[ \t]+$') { throw "trailing whitespace: $path" }
    if (-not $text.EndsWith("`n")) { throw "missing final newline: $path" }
}
$changed = git diff --name-only --diff-filter=ACMRT
$changed += git ls-files --others --exclude-standard
$changed = $changed | Where-Object { $_ -notlike '.pytest-tmp/*' } | Sort-Object -Unique
"===== COMPLETE REVIEW PATHS ====="
$changed
```

Expected: `pip check` and `git diff --check` exit `0`; tracked changes are reviewed through Git diff, and the two new untracked code files are printed in full and pass explicit trailing-whitespace/final-newline checks. The separately listed complete review paths are exactly the locked map plus the approved design, spec, and plan documents. Complete review finds no Skill body persistence, logging, permission change, unrelated refactor, weakened assertion, or deferred feature. Repository-local `.pytest-tmp` artifacts are not an accepted final state and must be absent before review; excluding their names from the review list does not waive the final clean-artifact requirement.

- [ ] **Step 11: Invoke required review and verification workflows**

Use `superpowers:requesting-code-review` for the completed core module without dispatching a subagent unless the current user explicitly authorizes delegation. Resolve only evidence-backed findings inside the locked scope and repeat affected tests. Then use `superpowers:verification-before-completion` and rerun Steps 2 through 10 if any code changed after their recorded output.

Expected: every accepted finding has a fresh RED/GREEN or documented non-code disposition; final evidence describes the exact current diff.

- [ ] **Step 12: Stop for user review without committing**

Confirm Task21 remains `进行中`. Do not stage, commit, push, invoke branch-finishing, or start Task22. Report:

- every RED command, nonzero exit code, and expected failure reason;
- every GREEN and regression command with actual counts;
- Windows symlink/junction/reparse evidence;
- schema v2 migration and ordered persistence evidence;
- session selection and immutable run snapshot evidence;
- instruction routing and unchanged summary behavior;
- zero-body persistence/logging evidence;
- offline, credential, dependency, framework, and deferred-scope audits;
- all warnings, skips, failures, deviations, or unverified items;
- final `git status --short --untracked-files=all` and `git diff --stat`.

---

## Final Acceptance Matrix

| Requirement | Implementation task | Fresh evidence |
|---|---:|---|
| User and workspace trusted roots | 1, 2 | `test_valid_skills_are_normalized_hashed_and_stably_sorted` |
| Restricted single-file format | 1 | malformed-entry parameter matrix |
| UTF-8/BOM, newline, raw byte limit | 1 | valid/BOM and invalid UTF-8/size tests |
| Exact CRLF/CR parsing and control handling | 1 | NEL preservation/hash plus VT/FF/DEL rejection tests |
| Stable sorting and diagnostics | 1 | repeated discovery equality and ordered diagnostic assertions |
| Malformed unrelated entry isolation | 1 | `test_malformed_entry_is_isolated_with_safe_diagnostic` |
| Duplicate ID has no precedence | 2 | `test_duplicate_id_across_sources_has_no_precedence` |
| Explicit ordered multi-selection | 2 | `test_resolve_preserves_explicit_order_and_hides_instruction_text` |
| Empty, invalid, duplicate, unavailable selection | 2 | invalid-selection parameter matrix |
| Exact 65,536-byte combined limit | 2 | exact-limit/first-byte-over test |
| Symlink/junction/reparse refusal | 2 | target Windows filesystem tests |
| Missing `LOCALAPPDATA` is safe | 2 | environment construction test |
| Unavailable source prevents non-empty resolution | 2 | one-source and both-source unavailable tests |
| Session selection persistence | 3 | ordered replacement tests |
| Schema v1 to v2 migration | 3 | migration preservation test |
| Safe per-run metadata only | 3 | snapshot tests and SQLite dump assertion |
| Missing parents and corrupt Skill rows are stable | 3 | parent-not-found and tampered-row tests |
| Frozen request carrier precedes controller use | 3A | request field type and hidden-repr test |
| Atomic first and follow-up creation | 3, 4 | store stale-selection and controller zero-side-effect tests |
| First run accepts selected IDs | 4 | first-run controller test |
| Selection only changes while idle | 4 | idle/reorder/clear and busy tests |
| Read-only catalog and selection APIs | 4 | controller query tests |
| Active run uses immutable snapshot | 4 | catalog-change-after-admission test |
| Next run resolves current catalog | 4 | follow-up selection test |
| Skill text reaches main model request | 5 | app/runtime propagation tests |
| No-selection behavior remains identical | 5 | explicit `None` compatibility test |
| Summary calls do not receive Skill | 5, 6 | context regression and source audit |
| Body hidden from repr/errors | 1, 2, 4, 5 | repr and failure privacy assertions |
| Body absent from DB/events/log/report | 3, 5, 6 | SQLite dump, outcome, source, and full regression evidence |
| Skills cannot add tools or bypass policy | 5, 6 | protected-module diff and Agent/safety/verification regressions |
| No SDK/network/key/dependency | 6 | offline child process, scans, and `pip check` |
| No executable plugin/MCP/market/GUI scope | 6 | deferred-scope scan and complete diff review |
| Task1–Task20 remain accepted | 6 | explicit component regression and full suite |
| Task21 waits for user review | 0, 6 | one `进行中`, final Git status, no commit |

## Plan Self-Review

- **Spec coverage:** Every requirement in sections 1–14 of the approved design maps to Tasks 1–6 and the acceptance matrix.
- **Type consistency:** `SkillCatalog.resolve()` returns `SkillInstructionBundle | None`; the same bundle type is carried by `SessionRunRequest`; store APIs receive `SkillDescriptor` metadata only; `execute_agent_run()` receives only `str | None`.
- **Persistence consistency:** `session_skill_selections` stores ordered IDs; `run_skill_snapshots` stores exactly ID, source, SHA-256, and character count; no read API requires unavailable name or description columns.
- **Ordering and byte boundaries:** Selection order remains caller order; database positions are one-based; combined byte acceptance is `<= 65_536`; the first disallowed byte is 65,537.
- **Lifecycle consistency:** Task 3A adds the frozen request carrier before controller TDD; first-run selection is an additive keyword; later selection changes require global controller availability and target `IDLE`; each admitted run receives one frozen bundle before worker creation.
- **Catalog availability consistency:** an absent directory is empty and readable; an unavailable source makes discovery unusable for every non-empty resolution, so no readable source receives implicit precedence.
- **Privacy consistency:** Instructions are hidden in repr and remain absent from SQLite, events, updates, logs, reports, and safe exceptions.
- **Scope consistency:** No Task22 transport, Task23 GUI, MCP, executable Skill, remote catalog, tool registration, policy change, or dependency is planned.
- **Placeholder scan:** The plan contains no unresolved implementation marker or vague substitute for a code/test step. Ellipses appear only in interface declarations that document return types without prescribing bodies.
- **Execution stop:** The plan ends at user review with Task21 still `进行中` and no Git write or remote action.

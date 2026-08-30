# Task21 Declarative Skill Catalog Design

**Date:** 2026-08-29  
**Status:** Approved design; implementation not started  
**Scope:** Task21 — declarative Skill catalog and selection

## 1. Objective

Task21 adds a trusted, local, declarative Skill catalog to MiniCodex. Users can
discover Skills from a user-level catalog and a workspace-level catalog, select
multiple Skills for a session in an explicit order, and use an immutable
instruction snapshot for each run.

The implementation preserves the existing provider-neutral Agent core. A Skill
is instruction text only. It cannot register code, add tools, change local
authorization, bypass verification, or alter termination budgets.

The feature is a backend capability for the future GUI. Task21 does not add a
Skill management screen.

## 2. Scope

Task21 implements:

- two trusted local Skill roots;
- deterministic discovery and parsing of `SKILL.md`;
- safe catalog diagnostics;
- explicit ordered selection of zero or more Skills;
- session-level persistence of selected Skill IDs;
- immutable in-memory instruction snapshots for each run;
- persistence of safe run snapshot metadata;
- integration with the existing `RunInstructionBuilder`;
- offline, deterministic tests for parsing, persistence, lifecycle, privacy,
  and security boundaries.

Task21 does not implement:

- GUI controls or drag-and-drop ordering;
- HTTP or SSE endpoints;
- Skill creation, editing, deletion, installation, or update workflows;
- remote download, marketplace, or discovery over the network;
- executable plugins, Python imports, PowerShell, or arbitrary scripts;
- MCP;
- Skill-defined tools or permissions;
- hot replacement of Skills in an active run;
- persistence of full Skill instruction bodies;
- Task22 or Task23 behavior.

## 3. Catalog Locations

The two roots are:

- user catalog: `%LOCALAPPDATA%\MiniCodex\skills\`;
- workspace catalog: `<workspace>\.coding-agent\skills\`.

The catalog constructor accepts both roots explicitly so tests use only
`tmp_path`. Production composition derives the user root from `LOCALAPPDATA`.
If the environment value or a present root is unavailable, discovery returns a
safe diagnostic for that source; it does not invent a fallback path or expose
the resolved absolute path. An absent catalog directory is different from an
unavailable source: absence is a readable empty catalog, while missing
`LOCALAPPDATA`, a present non-directory root, an unreadable root, or an unsafe
root-level reparse point makes global catalog uniqueness unknowable.

The workspace root is derived from the normalized configured workspace. A
missing catalog directory means that source contains no Skills. Discovery does
not create either directory.

## 4. Skill File Format

Each immediate child directory represents one Skill:

```text
<catalog-root>/
  code-review/
    SKILL.md
```

`SKILL.md` uses a restricted front matter followed by a non-empty instruction
body:

```markdown
---
id: code-review
name: Code Review
description: Review changes for correctness and safety.
---
Inspect the requested changes and report evidence-backed findings.
```

The parser enforces all of the following:

- the raw file is at most 65,536 bytes;
- the encoding is UTF-8 or UTF-8 with BOM;
- front matter begins at the first line;
- both delimiters are standalone `---` lines;
- the only fields are `id`, `name`, and `description`;
- every field occurs exactly once and has a non-empty, single-line value;
- `id` matches
  `[a-z0-9](?:[a-z0-9-]{0,62}[a-z0-9])?`;
- `id` exactly matches the parent directory name;
- `name` contains 1 through 80 Unicode code points;
- `description` contains 1 through 240 Unicode code points;
- the normalized instruction body is non-empty;
- NUL, DEL, and C0 control characters other than tab, CR, and LF are rejected.

Control validation runs on the decoded text before line parsing. The body is
normalized only by converting CRLF to LF, converting remaining CR to LF, and
stripping outer whitespace; parsing splits only on LF. `VT`, `FF`, and `DEL`
are therefore rejected rather than interpreted as line separators. Unicode
`NEL` (`U+0085`) is preserved as content. SHA-256 and character count are
computed after this exact normalization, so metadata describes the exact
instructions used to build the run prompt.

## 5. Discovery and Conflict Rules

Discovery scans only immediate child directories and never recursively searches
for Skills. Files beside `SKILL.md` are ignored and never imported or executed.

Valid descriptors are sorted by `skill_id`. Diagnostics are sorted by source,
entry name, and code. Filesystem enumeration order is never observable.

Malformed unrelated entries are skipped and produce safe diagnostics. Other
valid Skills remain available. Diagnostics contain only:

- a stable error code;
- `SkillSource.USER` or `SkillSource.WORKSPACE`;
- the immediate entry name.

Diagnostics never contain absolute paths, instruction text, raw front matter,
or an operating-system exception.

The same Skill ID appearing in both roots is a catalog conflict. There is no
source precedence and no silent override. The catalog view reports
`usable=False`, and any non-empty selection resolution fails with
`duplicate_skill_id`.

An unavailable source also makes the catalog view `usable=False`, even when
valid descriptors from the other source can still be displayed. An empty
selection resolves to `None` without requiring either catalog to be available.
Any non-empty selection against a view with an unavailable source fails with
`skill_catalog_unavailable`, including when the selected ID is visible in the
other source, because the catalog cannot prove cross-source uniqueness. When
both roots are readable and no duplicate conflict exists, a missing selected ID
fails with `selected_skill_unavailable`. These rules never assign implicit
precedence to a readable source.

## 6. Path and Trust Boundary

The catalog rejects a root, Skill directory, or `SKILL.md` that is a symbolic
link, junction, or other Windows reparse point. It also rejects path forms that
could reference outside the expected immediate directory, including absolute
paths, `..`, alternate data streams, and invalid case variants of a lowercase
Skill ID.

The workspace catalog remains inside Task8's protected `.coding-agent`
boundary. Agent filesystem tools cannot modify it. The user catalog is outside
the configured workspace and is therefore unreachable through Agent tools.

Skill instructions are trusted local prompt input, not deterministic authority.
Existing local code remains authoritative for:

- `ToolRegistry` contents;
- path and command authorization;
- command timeout and output limits;
- model, provider-attempt, tool, verification, and time budgets;
- completion-candidate handling;
- the Task11 verification gate and the only path to success.

## 7. Public Types and Interfaces

Task21 adds `src/coding_agent/skills.py` with the following public shape:

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


class SkillCatalogError(RuntimeError):
    code: str


class SkillCatalog:
    def __init__(
        self,
        *,
        user_root: Path,
        workspace_root: Path,
    ) -> None: ...

    def discover(self) -> SkillCatalogView: ...

    def resolve(
        self,
        skill_ids: tuple[str, ...],
    ) -> SkillInstructionBundle | None: ...
```

All dataclasses validate their own invariants. Instruction fields are hidden
from `repr`. `SkillCatalogError.__str__` and `repr` expose only a stable code.

`resolve()` validates tuple type, ID syntax, uniqueness, catalog usability,
selected-entry availability, and final combined size. It preserves the caller's
order. The combined text is:

```text
### Skill: <id> — <name>
<normalized body>
```

Selected sections are separated by two LF characters. The final combined text,
including headings and separators, must not exceed 65,536 UTF-8 bytes.

Stable resolution error codes are:

- `invalid_skill_selection`;
- `duplicate_skill_selection`;
- `duplicate_skill_id`;
- `selected_skill_unavailable`;
- `skill_selection_too_large`;
- `skill_catalog_unavailable`.

## 8. Controller Interfaces and Lifecycle

`SessionController` adds:

```python
def list_skills(self) -> SkillCatalogView: ...

def get_session_skills(
    self,
    session_id: str,
) -> tuple[str, ...]: ...

def set_session_skills(
    self,
    session_id: str,
    skill_ids: tuple[str, ...],
) -> tuple[str, ...]: ...

def create_session(
    self,
    message: str,
    *,
    skill_ids: tuple[str, ...] = (),
) -> RunHandle: ...
```

The additive keyword parameter preserves all existing `create_session(message)`
callers. `submit_message()` keeps its current signature and resolves the
selection persisted for that session.

`set_session_skills()` is permitted only when:

- the controller is open and not degraded;
- there is no admission operation or active run;
- the target session exists and has `SessionStatus.IDLE`;
- the complete ordered selection resolves successfully.

The controller briefly owns its existing admission boundary while changing a
selection. A failure leaves the previous selection unchanged.

`list_skills()` and `get_session_skills()` are read-only and may run while an
Agent run is active. Selection changes are forbidden while any run is active,
matching the single-active-run controller design.

Controller errors remain stable and safe. Skill catalog errors are translated
to `SessionControllerError` with the same code. Existing controller-state errors
have priority in this order:

1. `controller_closed` or `controller_degraded`;
2. `controller_busy`;
3. session existence and idle-state validation;
4. selection syntax and duplicate validation;
5. catalog conflict and selected-entry availability;
6. combined-size validation;
7. database persistence.

## 9. Database Schema and Atomicity

The SQLite schema version changes from 1 to 2. Initialization adds two tables:

```sql
CREATE TABLE IF NOT EXISTS session_skill_selections (
    session_id TEXT NOT NULL REFERENCES sessions(session_id),
    position INTEGER NOT NULL CHECK(position > 0),
    skill_id TEXT NOT NULL,
    PRIMARY KEY(session_id, position),
    UNIQUE(session_id, skill_id)
);

CREATE TABLE IF NOT EXISTS run_skill_snapshots (
    run_id TEXT NOT NULL REFERENCES session_runs(run_id),
    position INTEGER NOT NULL CHECK(position > 0),
    skill_id TEXT NOT NULL,
    source TEXT NOT NULL CHECK(source IN ('user', 'workspace')),
    sha256 TEXT NOT NULL CHECK(length(sha256) = 64),
    char_count INTEGER NOT NULL CHECK(char_count > 0),
    PRIMARY KEY(run_id, position),
    UNIQUE(run_id, skill_id)
);
```

Positions are one-based. Reads always order by `position`. Existing v1
databases migrate by adding the tables and setting `PRAGMA user_version = 2`.
Existing sessions therefore have empty selections.

Selection and snapshot read operations first verify that the parent session or
run exists. A missing parent produces the existing stable `session_not_found`
or `run_not_found` error instead of being confused with an empty child table.
Invalid persisted `source`, SHA-256, character-count, position, or identifier
data is mapped to the existing safe `database_corrupt` error.

The store adds provider-neutral operations to:

- read an ordered session selection;
- atomically replace an idle session selection;
- read ordered safe run snapshot records;
- accept safe Skill descriptor metadata during session creation and message
  submission.

First-run creation persists the session, selection, run, run snapshot metadata,
and lifecycle events in one transaction. Later submission rereads the persisted
selection inside its transaction and compares it exactly with the resolved
bundle IDs before inserting the run. A mismatch is rejected rather than
starting a worker with stale selection data.

No Skill body, combined prompt, absolute path, front matter text, or parser
exception is stored in SQLite. A run that fails during worker startup retains
its safe snapshot metadata because the metadata records the admitted run
configuration.

## 10. Immutable Run Snapshot and Agent Integration

`SessionRunRequest` gains a backward-compatible optional field:

```python
skill_bundle: SkillInstructionBundle | None = field(
    default=None,
    repr=False,
)
```

The run admission sequence is:

1. acquire the controller admission boundary;
2. receive first-run IDs or load the existing session selection;
3. call `SkillCatalog.resolve()` once and freeze the resulting bundle;
4. atomically persist the selection and safe run metadata;
5. construct `SessionRunRequest` with the in-memory bundle;
6. start the worker;
7. pass `bundle.text` through an additive `skill_instructions` keyword in
   `execute_agent_run()`;
8. call the existing
   `RunInstructionBuilder.build(workspace, skill_instructions=...)`;
9. provide only the final instruction string to `AgentRunner`.

Strings and frozen dataclasses make the active bundle immutable. Changes to a
catalog file after admission do not affect the run. The next run resolves the
current catalog contents again.

When no Skill is selected, `None` follows the existing path and produces exactly
the current instructions. Context-summary calls continue to use
`instructions=None`; Skill instructions are not repeated in summary prompts.

## 11. Failure Atomicity and Privacy

For `create_session()` and `submit_message()`, Skill resolution happens after
controller admission and before store mutation. If parsing, resolution, or
persistence fails:

- no session is created;
- no run is created;
- no lifecycle event is appended;
- no worker thread is started.

For selection replacement, all validation occurs before the transaction and the
database replacement is one transaction. A failure preserves the previous rows.

`KeyboardInterrupt` and `SystemExit` continue to propagate. Code catches only
the specific ordinary exceptions it can translate safely and never catches
`BaseException` as a catalog-recovery mechanism.

Skill bodies and combined instructions must not appear in:

- `repr` output;
- exception strings;
- session events;
- SQLite rows;
- JSONL audit logs;
- final reports;
- controller update payloads.

Safe metadata may expose Skill ID, source, order, SHA-256, and character count.

## 12. File Map

Create:

- `src/coding_agent/skills.py`
- `tests/test_skills.py`

Modify:

- `src/coding_agent/session_store.py`
- `src/coding_agent/session_runtime.py`
- `src/coding_agent/session_controller.py`
- `src/coding_agent/app.py`
- `tests/test_session_store.py`
- `tests/test_session_runtime.py`
- `tests/test_session_controller.py`
- `tests/test_app.py`
- `DESIGN.md`, only for the approved Task21 Skill-baseline amendment
- `TASKS.md`, only during implementation to move Task20 to `已完成` and
  Task21 to `进行中`

Do not modify unless a separately approved design change is required:

- message types;
- model clients;
- `AgentRunner` and Agent state;
- filesystem, shell, safety, verification, termination, or logging modules;
- CLI and configuration;
- dependency files;
- Task22 or Task23 modules.

## 13. Test Strategy

Implementation follows strict RED, GREEN, and regression cycles.

### 13.1 Catalog and Parser

Tests cover:

- missing and empty roots;
- valid Skills in both roots;
- deterministic descriptor and diagnostic order;
- UTF-8 BOM and newline normalization;
- exact CRLF/CR normalization, rejection of `VT`/`FF`/`DEL`, and preservation
  of `U+0085` in content and hashes;
- missing, duplicate, unknown, empty, or multiline metadata fields;
- invalid IDs and parent-directory mismatch;
- invalid UTF-8, raw byte overflow, empty body, NUL, DEL, and disallowed
  controls;
- malformed unrelated entries remaining isolated;
- safe diagnostics without absolute paths or content.

### 13.2 Conflict and Selection

Tests cover:

- duplicate IDs across roots;
- an unavailable user root, workspace root, or both roots with non-empty
  selection, including a selected ID visible in the other root;
- missing or malformed selected IDs;
- explicit order preservation;
- duplicate selection rejection;
- deterministic per-Skill and combined SHA-256 values;
- exact combined format;
- exact 65,536-byte acceptance and first-byte-over rejection;
- immutable snapshots and hidden `repr` values.

### 13.3 Filesystem Safety

Windows-focused tests cover symlink, junction, and reparse-point roots,
directories, and files. Tests also cover absolute paths, `..`, alternate data
streams, and invalid case variants. All test content stays within pytest
temporary directories, and no test reads the developer's real user catalog.

### 13.4 Store

Tests cover:

- fresh schema v2 initialization;
- v1 to v2 migration without losing existing sessions;
- rejection of a future schema version;
- ordered selection reads and uniqueness constraints;
- missing parent records and corrupt persisted Skill metadata;
- atomic replacement and rollback;
- first-run and later-run snapshot metadata;
- exact selection comparison during submission;
- no body text in any SQLite table;
- recovery and existing session behavior without Skills.

### 13.5 Controller and Runtime

Tests cover:

- first-run `skill_ids`;
- idle selection replacement and clearing;
- busy, closed, degraded, missing-session, and non-idle rejection;
- read-only catalog and selection queries during a run;
- resolution failures producing zero persistence and zero worker starts;
- a directory edit after admission not changing the active bundle;
- runtime propagation into `RunInstructionBuilder`;
- exact existing behavior when selection is empty;
- no Skill instructions in context-summary calls.

### 13.6 Security, Privacy, and Regression

Tests and audits prove:

- Skill text cannot change registered tools or deterministic policy objects;
- no network access or real API key use;
- no OpenAI SDK type enters catalog, session, or Agent interfaces;
- no executable plugin or Agent framework is introduced;
- no instruction body appears in repr, errors, events, logs, reports, or SQLite;
- Task1 through Task20 tests still pass;
- no new dependency is present;
- credential, placeholder, skip/xfail, framework, and deferred-scope scans are
  clean;
- `git diff --check` and complete diff review pass.

## 14. Acceptance Criteria

Task21 is ready for user review when all of the following have fresh evidence:

- both local roots are discovered deterministically;
- the restricted `SKILL.md` format and limits are enforced;
- malformed unrelated entries are isolated;
- duplicate IDs never receive silent precedence;
- ordered multi-Skill selection persists per session;
- only an idle controller can change selection;
- first-run selection is supported without breaking old callers;
- every run receives one immutable in-memory instruction bundle;
- safe ordered metadata is persisted for each run;
- full instruction text is never persisted or logged;
- active runs do not change when catalog files change;
- empty selection preserves Task20 behavior;
- existing security and verification enforcement remains authoritative;
- all focused, regression, full-suite, Windows safety, privacy, dependency, and
  diff checks pass.

At the implementation review checkpoint, Task21 remains `进行中`. There is no
automatic stage, commit, push, or transition to Task22.

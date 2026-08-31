# Local Skill Import and Session Deletion Design

**Date:** 2026-08-31

**Status:** Approved for inline execution in the current user turn

**Scope:** Task 27 — workspace declarative Skill zip import; Task 28 — per-session deletion with audit-log cleanup

## 1. Objective

This milestone adds two local GUI management capabilities without changing the
Agent loop or granting the model new authority:

1. import one trusted, declarative workspace Skill from a bounded zip archive;
2. delete one idle workspace session together with its persisted conversation,
   run records, Skill metadata, in-memory event projection, and audit JSONL
   files.

The two tasks share one approved design and one implementation plan, but remain
separate modules and test checkpoints. Task 27 must be completed and verified
before Task 28 starts. Task 26 remains the only task currently in progress;
Tasks 27 and 28 begin as `未开始`.

Neither task adds executable Skills, remote downloads, a marketplace, arbitrary
workspace deletion, or a model-facing deletion tool.

## 2. Locked product decisions

- The GUI imports a single `.zip`; browser directory selection is not supported.
- Import targets only `<workspace>/.coding-agent/skills/`, not the user catalog.
- An archive contains exactly one top-level Skill directory and one `SKILL.md`.
- Scripts, assets, references, nested directories, and any other archive member
  are rejected rather than silently retained.
- Existing Skill IDs are never overwritten or updated.
- Sessions are deleted individually with a title-bearing confirmation prompt.
- There is no bulk delete operation.
- Deleting a session also removes the audit JSONL files associated with its
  persisted `audit_run_id` values.
- Skill import and session deletion are unavailable while any run is active or
  while the controller is admitting another mutation.
- No production dependency is added.

## 3. Architecture

```text
static GUI
   |
   +-- POST /api/v1/skills/import (raw application/zip)
   |       `-- SessionController.import_skill_archive()
   |               `-- SkillPackageInstaller
   |                       `-- workspace Skill catalog root
   |
   `-- DELETE /api/v1/sessions/{session_id}
           `-- SessionController.delete_session()
                   `-- SessionDeletionService
                           +-- SQLiteSessionStore
                           +-- audit log directory
                           +-- deletion staging/recovery
                           `-- SessionEventHub forgetting
```

`SkillCatalog` remains the read-only owner of discovery and selection
resolution. `SkillPackageInstaller` owns archive validation and safe catalog
mutation. `SQLiteSessionStore` owns relational deletion. A separate
`SessionDeletionService` coordinates the database with exact audit-log paths and
crash recovery. The Web layer remains a thin authenticated adapter.

## 4. Task 27: declarative Skill zip import

### 4.1 Public boundary

Task 27 adds `src/coding_agent/skill_packages.py` with a focused public shape:

```python
class SkillPackageError(RuntimeError):
    code: str


class SkillPackageInstaller:
    def inspect(self, archive: bytes) -> SkillDescriptor: ...
    def install(self, archive: bytes) -> SkillDescriptor: ...
```

`SessionController` receives an injected installer and exposes:

```python
def import_skill_archive(self, archive: bytes) -> SkillDescriptor: ...
```

The controller uses its existing admission reservation, so import is rejected
when a run or another admitted mutation is active. `inspect()` performs the
complete bounded archive parse without creating the catalog root, staging
directory, destination, or any other file. Before calling `install()`, the
controller discovers the complete user-plus-workspace catalog, requires
`view.usable`, and rejects the candidate ID when it is already present in either
source. These preflight rejections therefore have zero filesystem writes.

After installation the controller rediscovers the catalog and requires the
returned descriptor to be the one unique matching descriptor. A catalog change
that races after the preflight produces the stable `skill_install_failed`
error. Because publication has already completed, that error preserves the
published workspace Skill and reports no rollback.

### 4.2 HTTP contract

The new route is:

```http
POST /api/v1/skills/import
Authorization: Bearer <memory-only-token>
Content-Type: application/zip

<raw zip bytes>
```

The request does not use `multipart/form-data`; FastAPI therefore needs no
`python-multipart` dependency. The existing bounded-body middleware remains the
outer cap, and `MAX_SKILL_ARCHIVE_BYTES` is exactly 131,072 bytes. Missing or
empty bodies, `Content-Encoding`, and media types other than
`application/zip` are rejected before the controller call.

Success returns HTTP 201 with the existing public Skill descriptor projection.
The response never includes archive bytes, instruction text, a temporary name,
or an absolute path.

### 4.3 Archive grammar

The only accepted logical members are:

```text
<skill-id>/
<skill-id>/SKILL.md
```

The explicit directory member is optional. The file member is mandatory and
unique. The Skill ID uses the existing lowercase ID grammar and must equal the
`id` field inside `SKILL.md`.

Validation rejects:

- more than one file or top-level directory;
- nested directories or any file other than `SKILL.md`;
- empty names, absolute names, drive-prefixed names, `..`, `.`, empty path
  segments, backslashes, colons, NUL, control characters, or alternate data
  stream forms;
- duplicate raw names or duplicate normalized names;
- encrypted members, unsupported general-purpose flags, or unsupported
  compression methods; the data-descriptor flag is accepted only when the
  central directory provides bounded compressed and uncompressed sizes;
- symbolic-link, junction-like, device, FIFO, socket, or other non-regular
  external attributes;
- a declared or actual uncompressed `SKILL.md` larger than 65,536 bytes;
- a malformed central directory, truncated data, CRC failure, or trailing
  archive structure that the standard-library reader rejects.

Only `ZIP_STORED` and `ZIP_DEFLATED` are accepted. The implementation never
calls an archive-wide extraction API. It reads the one validated member with a
65,537-byte bounded read, then writes a fresh local `SKILL.md`; archive path
metadata is never trusted as a filesystem destination. The raw archive cap and
uncompressed member cap bound memory and decompression work.

### 4.4 Shared Skill parsing

The current `skills.py` parser is refactored so one private, deterministic
bytes-to-definition function owns UTF-8, front matter, metadata, normalization,
size, control-character, hash, and character-count rules. Filesystem discovery
performs its existing lstat/reparse checks and then calls that parser. The
installer calls the same parser on the bounded archive member.

This refactor must preserve every existing Task 21 behavior and diagnostic.
Import cannot create a second, more permissive Skill format.

### 4.5 Atomic installation

The installer normalizes and verifies the workspace Skill root, rejecting a
root or ancestor that is a reparse point or not a real directory. A missing
workspace catalog root may be created by this dedicated local service.

Installation then:

1. validates the complete archive and parses `SKILL.md` in memory;
2. returns that descriptor from the no-write `inspect()` boundary so the
   controller can complete the catalog preflight;
3. revalidates the immutable archive bytes inside `install()`;
4. verifies that `<workspace>/.coding-agent/skills/<skill-id>` does not exist;
5. creates a randomly named staging directory directly inside the catalog root;
6. creates `SKILL.md` with exclusive-create semantics and bounded bytes;
7. rereads and reparses the staged file;
8. atomically renames the staging directory to `<skill-id>` without overwrite;
9. returns the installed descriptor for the controller's post-publication
   catalog check.

Any pre-rename failure removes only the exact validated staging directory. A
rename race becomes `skill_already_exists`; it never overwrites the winner.
Post-rename discovery failure leaves the valid installed file in place and
returns a stable catalog or install error rather than claiming rollback.

## 5. Task 28: session and audit-log deletion

### 5.1 Public boundary

Task 28 adds `src/coding_agent/session_deletion.py` with a coordinator that is
injected into `SessionController`:

```python
@dataclass(frozen=True, slots=True)
class SessionDeletionResult:
    session_id: str
    run_ids: tuple[str, ...] = field(repr=False)
    cleanup_pending: bool


class SessionDeletionError(RuntimeError):
    code: str


class SessionDeletionService:
    @property
    def workspace(self) -> Path: ...

    @property
    def store(self) -> SessionStore: ...

    def recover_pending(self) -> None: ...
    def delete(self, session_id: str) -> SessionDeletionResult: ...
```

`SessionController.open()` accepts a provider-neutral
`SessionDeletionServiceFactory = Callable[[Path, SessionStore],
SessionDeletionService]`. It invokes that factory only after creating and
initializing its internal store, passes that exact store object to the factory,
and rejects a returned service unless `service.store is store` and its
normalized workspace identity matches the store workspace. Startup recovery
therefore cannot accidentally operate through a separately opened database
handle.

`SessionController.delete_session()` reserves admission, rejects a non-idle
session or any globally active run, delegates to the service, and passes the
result's validated `run_ids` to `SessionEventHub.forget_runs()` after durable
database deletion. The Web projection omits `run_ids`.

`SessionEventHub.forget_runs()` clears only the retained projection that
matches a deleted run. Under its condition lock it resets exactly the six
existing state items: `_session_id`, `_run_id`, `_events`,
`_lifecycle_updates`, `_retained_bytes`, and `_next_sequence`. No terminal
marker exists or is introduced by Task 28.

### 5.2 Store contract and relational deletion

`SessionStore` gains three deterministic public operations:

```python
def get_session_deletion_manifest(
    self, session_id: str
) -> SessionDeletionManifest: ...

def session_exists(self, session_id: str) -> bool: ...

def delete_session(
    self, manifest: SessionDeletionManifest
) -> None: ...
```

The immutable manifest contains the session ID, all session run IDs, and the
non-null audit run IDs in stable ordinal order. IDs are validated with the same
32-lowercase-hex grammar used by the logger. It contains no log paths.

`delete_session()` starts `BEGIN IMMEDIATE`, rereads the session and exact
manifest, and rejects stale or mismatched input. It requires the session to be
idle and no workspace run to be active. In the same transaction it deletes:

1. `session_events` by session ID;
2. `run_skill_snapshots` by the manifest run IDs;
3. `session_runs` by session ID;
4. `session_skill_selections` by session ID;
5. the `sessions` row.

Every affected row count and the final absence of dependent rows are checked
before commit. Any mismatch or SQLite failure rolls the transaction back. The
schema is not migrated to `ON DELETE CASCADE`; explicit order keeps destructive
scope visible and testable.

### 5.3 Exact log targets

An audit file is derived only as:

```text
<workspace>/.coding-agent/logs/<audit_run_id>.jsonl
```

Database `log_path` text, user input, globs, directory enumeration, and archive
paths are never used as deletion targets. The workspace, `.coding-agent`, logs,
staging root, every existing log file, and every staging directory undergo
normalization plus reparse checks before mutation. A missing expected log means
it was already absent and is recorded as such; it does not widen the target
set. An unexpected type or reparse point fails before database deletion.

### 5.4 Reversible staging and crash recovery

SQLite and NTFS do not share a transaction. Task 28 therefore uses
`<workspace>/.coding-agent/deletion-staging/<operation-id>/` and a bounded JSON
manifest containing only schema version, operation ID, session ID, validated
audit IDs, and the exact audit IDs whose files existed and are scheduled for
staging. The service determines that subset before the first move and publishes
the manifest atomically, so recovery can distinguish an unattempted move from
an unrelated file even after a partial staging crash.

Deletion proceeds as follows:

1. obtain and validate the store manifest;
2. validate every exact source and record the existing-source subset in an
   atomically published bounded staging manifest before moving any log;
3. atomically move each recorded exact log into that operation directory;
4. call the store's transactional deletion with the unchanged manifest;
5. if the database call fails, atomically restore every staged log and report
   failure;
6. if the database commit succeeds, delete only the staged files, manifest,
   and now-empty exact operation directory;
7. if final physical cleanup fails, return `cleanup_pending=True`; the session
   is durably deleted and the logs no longer exist at their public audit paths.

`recover_pending()` runs during controller startup before new work is admitted.
For each strictly validated operation directory:

- if its session still exists, restore the staged files without overwrite;
- if its session no longer exists, finish deleting the staged files;
- if a manifest is missing but the validated operation directory is empty,
  remove that empty directory;
- if a manifest is malformed, a target conflicts, or any path is unsafe, fail
  closed with `session_deletion_recovery_failed` and do not guess.

When the session still exists, a recorded ID with no staged file is valid only
when its exact public log still exists, meaning the move had not happened. When
the session no longer exists, recovery evaluates each recorded ID using the
exact public/staged pair: staged present and public absent is deleted; both
absent means cleanup for that ID already completed and is accepted; public
present with staged absent fails closed; and both present also fails closed.
The controller opens in a degraded/unavailable state when recovery cannot be
completed safely. Recovery never enumerates or deletes ordinary audit logs.

### 5.5 HTTP contract

The new route is:

```http
DELETE /api/v1/sessions/{session_id}
Authorization: Bearer <memory-only-token>
```

It accepts no request body. Success returns HTTP 200:

```json
{
  "session_id": "<id>",
  "deleted": true,
  "cleanup_pending": false
}
```

When final staging cleanup is pending, the same successful response sets
`cleanup_pending` to true and adds the fixed warning code
`session_log_cleanup_pending`. A failure before durable database deletion uses
the ordinary stable error envelope and never reports `deleted=true`.

## 6. GUI behavior

The existing Skills panel adds:

- an `导入 Skill` button;
- one hidden file input with `.zip` acceptance;
- an empty-catalog explanation;
- a bounded importing state and stable result message.

The client sends the selected `File` as a raw request body while setting
`Content-Type: application/zip`. After success it refreshes the catalog. For a
new-session draft it adds the new ID to draft selection. For an idle selected
session it uses the existing selection endpoint to append the new ID. It never
silently changes an active session.

Each session row adds a separate delete control. Activating it opens a native or
existing local confirmation surface that includes the plain-text session title.
Cancelling sends no request. Confirming deletion disables repeated actions.
After success the GUI removes the row and:

- selects the next visible session when the deleted session was selected;
- otherwise selects the previous visible session;
- returns to the new-session empty state when no sessions remain;
- leaves the current selection unchanged when another row was deleted.

`cleanup_pending` displays a non-secret warning that physical log cleanup will
retry at startup. Import and delete controls are disabled whenever any session
is running or cancelling. All server and session text continues through safe
text-node rendering, never `innerHTML`.

## 7. Stable errors and privacy

Task 27 uses stable public codes including:

- `skill_archive_too_large`;
- `invalid_skill_archive`;
- `unsafe_skill_archive`;
- `skill_already_exists`;
- `skill_install_failed`.

The import route uses this locked route-specific HTTP mapping for import
failures:

- `invalid_skill_archive` and `unsafe_skill_archive` -> HTTP 400;
- `skill_catalog_unavailable`, `skill_already_exists`, and `controller_busy` ->
  HTTP 409;
- `skill_install_failed` -> HTTP 500;
- `skill_archive_too_large` keeps the existing bounded-body HTTP 413 contract.

The route-specific `skill_catalog_unavailable` mapping does not change the
existing status used by non-import Skill catalog operations.

Task 28 uses stable public codes including:

- existing `session_not_found`, `invalid_session_state`, and `controller_busy`;
- `session_delete_failed`;
- `session_deletion_recovery_failed`;
- successful warning `session_log_cleanup_pending`.

Errors, reprs, REST, SSE, GUI, JSONL, and tests must not expose archive bytes,
Skill instructions, absolute paths, staging names, OS exception text, audit-log
content, credentials, or provider data. Public responses may expose the same
safe Skill descriptor and session IDs already exposed by the GUI.

## 8. Testing strategy

### 8.1 Task 27 unit and component tests

- accepted stored and deflated archives, with and without a directory member;
- raw and uncompressed equality boundaries;
- missing, duplicate, nested, multiple, extra, encrypted, unsupported, corrupt,
  truncated, CRC-invalid, oversized, and compression-bomb-shaped archives;
- absolute, drive, ADS, traversal, dot-segment, empty-segment, backslash,
  control-character, and duplicate-normalized member names;
- external attributes representing symlinks or non-regular files;
- shared parser equivalence with manual catalog discovery;
- missing catalog creation, unsafe roots, duplicate installed IDs, rename races,
  exclusive creation, staging cleanup, and post-rename discovery failure;
- no-write inspection, unusable-catalog and cross-source duplicate-ID
  preflight rejection, plus post-publication race preservation;
- controller admission, closed/degraded states, catalog consistency, and exact
  import HTTP status mapping.

### 8.2 Task 28 unit and component tests

- deletion of every relational row for one session while another is unchanged;
- stable manifest ordering, stale-manifest rejection, row-count checks, rollback,
  busy database mapping, missing session, active session, and global active run;
- exact audit-ID path construction, missing log acceptance, unrelated log
  preservation, and rejection of reparse or non-regular targets;
- staging, restore after database failure, cleanup after commit, cleanup-pending
  success, and no overwrite during restore;
- crash recovery before moves, after partial moves, before database deletion,
  after database commit, and after partial physical cleanup;
- deleted-session recovery accepts an already-cleaned public/staged pair while
  rejecting a surviving public file whose staged counterpart is missing;
- malformed manifests and unsafe staging fail closed;
- matching `SessionEventHub` projection is forgotten while unrelated state is
  preserved.

### 8.3 REST and GUI tests

- Bearer, Host, Origin, body cap, exact media type, content encoding, response
  projection, error status, and no-secret contracts;
- raw zip upload, catalog refresh, auto-selection, empty state, repeated-click
  suppression, and active-run disabling;
- title-bearing confirmation, cancel-without-request, selected and unselected
  deletion, next/previous selection, last-session empty state, API failure, and
  cleanup-pending warning;
- packaged-resource and no-external-resource regression tests.

All default tests remain offline and use no API key. No live model, network,
package installation, or external zip tool is required.

## 9. Documentation and roadmap

Implementation updates `DESIGN.md`, `TASKS.md`, `README.md`, `README.txt`, and
`docs/USAGE.md`. Task 27 and Task 28 remain `未开始` until their individual
implementation checkpoints begin. Only one may be `进行中` at a time, and Task
28 cannot begin until Task 27 acceptance tests pass and Task 27 is marked
`已完成`.

The implementation plan is approved in this user turn for inline execution with
`superpowers:executing-plans`. It must use TDD for each behavioral slice,
request code review after each core module, run the complete Python and Node.js
regressions before either task is marked complete, and use
verification-before-completion before a task status changes to `已完成`. It does
not depend on an unavailable execution skill.

## 10. Explicit non-goals

- executable Skills, Skill-defined tools or permissions, MCP, remote Skill
  download, marketplace browsing, user-catalog installation, Skill update,
  overwrite, edit, or uninstall;
- importing arbitrary Skill assets or retaining ignored archive content;
- bulk session deletion, archive, rename, undo after committed deletion, or
  deleting sessions during a run;
- exposing deletion as an Agent tool or allowing the model to name deletion
  targets;
- deleting arbitrary workspace files, unrelated audit logs, SQLite files, WAL
  files, or protected internal directories;
- a claim of operating-system sandboxing or cross-filesystem atomicity.

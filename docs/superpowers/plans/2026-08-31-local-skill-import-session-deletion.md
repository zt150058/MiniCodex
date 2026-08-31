# Local Skill Import and Session Deletion Implementation Plan

> **For agentic workers:** APPROVED EXECUTION: Use `superpowers:executing-plans` inline in the current task and follow every checkpoint below. No unavailable skill is an execution prerequisite.

**Goal:** Add authenticated GUI import of one pure declarative workspace Skill zip, then add confirmed per-session deletion that also removes exact audit JSONL files with reversible staging and startup recovery.

**Architecture:** Task 27 introduces a focused `SkillPackageInstaller` beside the existing read-only `SkillCatalog`, using one shared Skill bytes parser and atomic catalog publication. Task 28 introduces explicit relational deletion in `SQLiteSessionStore` plus a `SessionDeletionService` that coordinates exact audit-log staging, database commit, crash recovery, and `SessionEventHub` forgetting through the existing single-admission controller.

**Tech Stack:** Python 3.11+, standard-library `zipfile`, `sqlite3`, FastAPI/Starlette, vanilla HTML/CSS/JavaScript, pytest, HTTPX, and Node.js `node:test`.

**Spec:** `docs/superpowers/specs/2026-08-31-local-skill-import-session-deletion-design.md`

## Global Constraints

- Read `AGENTS.md`, `DESIGN.md`, `TASKS.md`, and the spec before implementation.
- Task 26 must be fully verified and marked `已完成` before Task 27 changes begin.
- Keep Task 27 and Task 28 sequential: only one task may be `进行中`; Task 28 starts only after Task 27 is verified and marked `已完成`.
- The user approved this plan for inline execution in the current turn. User-authorized read-only review subagents may assist at explicit checkpoints, but implementation remains sequential and does not depend on a subagent-only skill.
- Do not use an Agent framework, Agent SDK, server-hosted file execution, worktree, parallel core-module work, network call, real API key, package installation, or new dependency.
- Preserve all unrelated dirty-worktree changes. Stop if an intended edit overlaps an unexplained user change that cannot be safely preserved.
- Use `apply_patch` for source and documentation edits.
- Keep the Agent's filesystem tools unchanged; Skill import and session deletion are local control-plane operations only.
- Normalize and validate every path; reject workspace escape and every reparse/symlink target named by the spec.
- Never use globs, database `log_path` text, archive extraction paths, shell commands, or user paths to choose deletion targets.
- Keep shell execution outside these features; all test commands have the existing test runner's timeout and output limits.
- Add or update tests before each behavioral implementation slice and run the stated RED command before GREEN.
- Do not weaken existing tests or add permanent skips/xfails.
- Do not commit, push, or operate on a remote unless the user separately authorizes it.
- Request code review after each core module and use verification-before-completion before changing a task status to `已完成`.

---

## File Responsibility Map

**New production files**

- `src/coding_agent/skill_packages.py`: bounded zip grammar, member validation, exclusive staging, atomic Skill publication, and stable Skill-package errors.
- `src/coding_agent/session_deletion.py`: exact log targets, bounded staging manifests, reversible moves, cleanup-pending result, and startup recovery.

**Existing production files**

- `src/coding_agent/skills.py`: one shared bytes parser used by discovery and import.
- `src/coding_agent/session_store.py`: immutable deletion manifest plus explicit transactional relational deletion.
- `src/coding_agent/session_events.py`: forget only the retained projection for specified deleted run IDs.
- `src/coding_agent/session_controller.py`: admission gates, dependency identity checks, import/delete public methods, startup deletion recovery, and stable error translation.
- `src/coding_agent/web.py`: route-specific media policy, raw zip endpoint, DELETE endpoint, and safe result serialization.
- `src/coding_agent/web_static/index.html`: import controls, empty Skill state, per-session delete control, and accessible status regions.
- `src/coding_agent/web_static/app.js`: raw authenticated upload, delete API call, controller state transitions, confirmation, refresh, selection, and cleanup warning.
- `src/coding_agent/web_static/styles.css`: compact import/delete/status styling and disabled/focus states.

**New tests**

- `tests/test_skill_packages.py`: archive and atomic-install boundary.
- `tests/test_session_deletion.py`: filesystem/database coordinator and crash recovery.

**Existing tests**

- `tests/test_skills.py`: parser equivalence and Task 21 regressions.
- `tests/test_session_store.py`: deletion manifest and transactional row removal.
- `tests/test_session_events.py`: exact projection forgetting.
- `tests/test_session_controller.py`: import/delete admission and dependency wiring.
- `tests/test_web_api.py`, `tests/web_support.py`: REST contract and recording controller.
- `tests/js/web_gui.test.mjs`, `tests/test_web_gui.py`: browser behavior and packaged static contracts.
- `tests/test_docs.py`, `tests/test_cli.py`: roadmap, dependency, and documentation contracts.

---

### Task 0: Reconfirm the approved baseline and activate Task 27

**Files:**

- Read: `AGENTS.md`
- Read: `DESIGN.md`
- Read: `TASKS.md`
- Read: `docs/superpowers/specs/2026-08-31-local-skill-import-session-deletion-design.md`
- Read: `docs/superpowers/plans/2026-08-31-local-skill-import-session-deletion.md`
- Modify: `TASKS.md`

**Interfaces:**

- Consumes: approved Task 26 repository state and the Task 27/28 spec.
- Produces: a recorded clean execution gate with Task 27 as the only `进行中` task.

- [ ] **Step 1: Inspect task status and the dirty baseline**

Run:

```powershell
git status --short
rg -n "^## 26\.|^## 27\.|^## 28\.|`进行中`|`未开始`|`已完成`" TASKS.md
git diff -- DESIGN.md TASKS.md AGENTS.md
```

Expected: Task 26 is `已完成`, Tasks 27 and 28 are `未开始`, and no unexplained overlapping edits block the planned files. If Task 26 is still `进行中`, stop without editing.

- [ ] **Step 2: Run the pre-feature focused baseline**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests/test_skills.py tests/test_session_store.py tests/test_session_events.py tests/test_session_controller.py tests/test_web_api.py tests/test_web_gui.py
node --test tests/js/web_gui.test.mjs
```

Expected: PASS with exit code 0. Record any environment-specific skip exactly; do not continue on a failure.

- [ ] **Step 3: Mark only Task 27 in progress**

Use `apply_patch` to change Task 27 from `未开始` to `进行中`. Leave Task 28 as `未开始` and Task 26 as `已完成`.

- [ ] **Step 4: Review checkpoint**

Run:

```powershell
git diff --check -- TASKS.md
```

Expected: exit code 0. Do not commit.

---

### Task 1: Extract one deterministic Skill bytes parser

**Files:**

- Modify: `src/coding_agent/skills.py`
- Modify: `tests/test_skills.py`

**Interfaces:**

- Consumes: `SkillSource`, `SkillDescriptor`, `_EntryError`, `MAX_SKILL_FILE_BYTES`.
- Produces: `_parse_skill_document(raw: bytes, source: SkillSource, entry_name: str) -> _SkillDefinition`; filesystem discovery continues through `_read_definition(path, source, entry_name)`.

- [ ] **Step 1: Add parser-equivalence and exact-error tests**

Add tests that build one raw document and prove direct parsing and catalog discovery return identical descriptor, normalized body hash, and character count. Also parameterize invalid UTF-8, 65,537 bytes, invalid control characters, invalid front matter, ID mismatch, and empty body through `_parse_skill_document` and assert the existing `_EntryError.code` values.

Use this representative assertion shape:

```python
raw = (
    b"---\r\n"
    b"id: review\r\n"
    b"name: Review\r\n"
    b"description: Review safely.\r\n"
    b"---\r\n"
    b"first\r\nsecond\r\n"
)
parsed = skills_module._parse_skill_document(
    raw, SkillSource.WORKSPACE, "review"
)
assert parsed.instructions == "first\nsecond"
assert parsed.descriptor == discovered
```

- [ ] **Step 2: Run RED**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests/test_skills.py -k "parse_skill_document or parser_equivalence"
```

Expected: FAIL because `_parse_skill_document` does not exist.

- [ ] **Step 3: Move byte parsing without changing semantics**

Implement the exact split:

```python
def _parse_skill_document(
    raw: bytes,
    source: SkillSource,
    entry_name: str,
) -> _SkillDefinition:
    if not isinstance(raw, bytes):
        raise TypeError("raw must be bytes")
    if len(raw) > MAX_SKILL_FILE_BYTES:
        raise _EntryError("skill_file_too_large")
    # Decode UTF-8-SIG, validate controls, parse exact front matter,
    # normalize only CRLF/CR and outer whitespace, then build descriptor.
```

Keep `_read_definition()` responsible only for lstat/reparse/regular-file checks and the bounded read, then return `_parse_skill_document(raw, source, entry_name)`. Preserve all existing codes and sorting behavior byte-for-byte.

- [ ] **Step 4: Run GREEN and Task 21 regression**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests/test_skills.py tests/test_instructions.py
```

Expected: PASS with exit code 0.

- [ ] **Step 5: Review checkpoint**

Inspect the diff and confirm no parser limit, normalization rule, descriptor field, public repr, or diagnostic code changed. Do not commit.

---

### Task 2: Implement the bounded Skill package installer

**Files:**

- Create: `src/coding_agent/skill_packages.py`
- Create: `tests/test_skill_packages.py`

**Interfaces:**

- Consumes: `_parse_skill_document`, `SkillDescriptor`, `SkillSource.WORKSPACE`, existing Skill ID grammar and `MAX_SKILL_FILE_BYTES`.
- Produces: `MAX_SKILL_ARCHIVE_BYTES = 131_072`, `SkillPackageError(code)`, and `SkillPackageInstaller(workspace_skill_root: Path, *, id_factory: Callable[[], str] = uuid4_hex)` with `inspect(archive: bytes) -> SkillDescriptor` and `install(archive: bytes) -> SkillDescriptor`.

- [ ] **Step 1: Create legal-archive helpers and happy-path tests**

Create a test helper using `io.BytesIO` and `zipfile.ZipFile` that emits exactly `review/SKILL.md`, optionally preceded by `review/`. Test both `ZIP_STORED` and `ZIP_DEFLATED`, directory-member presence/absence, deterministic descriptor fields, missing catalog creation, and exact staged-content bytes. Call `inspect()` first and assert it returns the descriptor while the workspace catalog root and destination are still absent.

Representative test:

```python
descriptor = SkillPackageInstaller(
    tmp_path / ".coding-agent" / "skills",
    id_factory=lambda: "1" * 32,
).inspect(make_skill_zip("review"))
assert descriptor.skill_id == "review"
assert not (tmp_path / ".coding-agent").exists()

descriptor = SkillPackageInstaller(
    tmp_path / ".coding-agent" / "skills",
    id_factory=lambda: "1" * 32,
).install(make_skill_zip("review"))
assert (tmp_path / ".coding-agent/skills/review/SKILL.md").is_file()
assert not (
    tmp_path / ".coding-agent" / "skills" / (".import-" + "1" * 32)
).exists()
```

- [ ] **Step 2: Run happy-path RED**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests/test_skill_packages.py -k "stored or deflated or catalog"
```

Expected: FAIL with import error because `coding_agent.skill_packages` does not exist.

- [ ] **Step 3: Add public types and full pre-write archive validation**

Implement stable-code exceptions whose `str` and `repr` contain only the code. Put the complete in-memory archive parse behind one private helper used by both public methods. `inspect()` returns the parsed descriptor and must not create, remove, rename, or write any filesystem object. `install()` reuses the same parser before any filesystem mutation. Validate `type(archive) is bytes`, non-empty size `<= 131_072`, a readable central directory, supported flag mask, no encryption, compression in `{ZIP_STORED, ZIP_DEFLATED}`, bounded central sizes, allowed external mode, and the exact normalized member set.

Lock the member parser to this shape:

```python
parts = info.filename.split("/")
if info.is_dir():
    valid = len(parts) == 2 and parts[1] == ""
else:
    valid = len(parts) == 2 and parts[1] == "SKILL.md"
```

Before that split reject NUL/control characters, `\\`, `:`, absolute/drive forms, `.`, `..`, empty interior segments, raw duplicates, and normalized duplicates. Read only the validated file member with `handle.read(MAX_SKILL_FILE_BYTES + 1)`, require EOF and CRC success, then call `_parse_skill_document(raw, SkillSource.WORKSPACE, skill_id)`.

- [ ] **Step 4: Add malicious-archive RED cases**

Parameterize missing file, multiple files, multiple roots, nested file, extra file, duplicate member, absolute path, drive path, ADS, traversal, dot/empty segment, backslash, control character, encrypted flag, unsupported flag, unsupported compression, symlink/non-regular external mode, declared oversize, actual oversize, CRC damage, truncated archive, and 131,073 raw bytes. Assert only:

```python
with pytest.raises(SkillPackageError) as captured:
    installer.install(archive)
assert captured.value.code in {
    "skill_archive_too_large",
    "invalid_skill_archive",
    "unsafe_skill_archive",
}
assert str(tmp_path) not in repr(captured.value)
```

- [ ] **Step 5: Run malicious RED, implement exact code mapping, then GREEN**

Run before and after implementation:

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests/test_skill_packages.py
```

Expected before: one or more new cases FAIL. Expected after: PASS.

- [ ] **Step 6: Add atomic publication failure tests**

Cover existing destination, unsafe catalog root, unsafe Skill destination, deterministic staging collision, exclusive file-create failure, reparsing failure, rename race, pre-rename cleanup, and successful post-rename descriptor return. The installer must write a fresh `SKILL.md` rather than extract archive paths and must not perform catalog-wide discovery; Task 3 owns post-publication catalog validation.

- [ ] **Step 7: Implement staging and atomic rename**

Use the exact root-local sequence:

```python
staging = root / f".import-{validated_operation_id}"
destination = root / descriptor.skill_id
staging.mkdir(exist_ok=False)
try:
    with (staging / "SKILL.md").open("xb") as handle:
        handle.write(raw)
    reread = _read_definition(staging / "SKILL.md", SkillSource.WORKSPACE, descriptor.skill_id)
    if reread.descriptor != descriptor:
        raise SkillPackageError("skill_install_failed")
    staging.rename(destination)
except FileExistsError:
    raise SkillPackageError("skill_already_exists") from None
finally:
    # Remove only the exact validated staging directory when publication did not occur.
```

Validate every root/parent/destination/staging component with lstat and the existing Windows reparse policy before mutation. Do not recursively remove any unresolved or non-empty unexpected target.

- [ ] **Step 8: Run Task 2 GREEN**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests/test_skill_packages.py tests/test_skills.py tests/test_path_safety.py
```

Expected: PASS with exit code 0.

- [ ] **Step 9: Request core-module code review**

Use `superpowers:requesting-code-review` on `skills.py`, `skill_packages.py`, and their tests. Apply only evidence-backed findings, rerun Step 8, and do not commit.

---

### Task 3: Wire Skill import through the single-admission controller

**Files:**

- Modify: `src/coding_agent/session_controller.py`
- Modify: `tests/test_session_controller.py`

**Interfaces:**

- Consumes: `SkillPackageInstaller.inspect/install(bytes) -> SkillDescriptor`, `SkillCatalog.discover()`.
- Produces: constructor/open injection `skill_installer: SkillPackageInstaller | None = None` and `SessionController.import_skill_archive(archive: bytes) -> SkillDescriptor`.

- [ ] **Step 1: Add dependency-identity and admission RED tests**

Test default installer composition, injected exact type, mismatched workspace root, successful import, catalog re-discovery mismatch, `controller_busy`, `controller_closed`, `controller_degraded`, and release of admission after every error. Add an unusable preflight catalog and a usable catalog containing the candidate ID from the user source; both must reject before `install()` and before the workspace catalog root exists. A blocking fake installer must prove a concurrent create/selection/import receives `controller_busy`. Add a post-publication catalog-race fake: `install()` publishes successfully, the second discovery becomes unusable or duplicated, the controller returns `skill_install_failed`, and the published workspace file remains present.

- [ ] **Step 2: Run RED**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests/test_session_controller.py -k "skill_archive or skill_installer or import_skill"
```

Expected: FAIL because the constructor parameter and method do not exist.

- [ ] **Step 3: Implement controller composition and method**

Follow the existing catalog pattern:

```python
def import_skill_archive(self, archive: bytes) -> SkillDescriptor:
    admission = self._reserve_admission()
    try:
        candidate = self._skill_installer.inspect(archive)
        before = self._skill_catalog.discover()
        if not before.usable:
            raise SessionControllerError("skill_catalog_unavailable")
        if any(item.skill_id == candidate.skill_id for item in before.skills):
            raise SessionControllerError("skill_already_exists")
        descriptor = self._skill_installer.install(archive)
        view = self._skill_catalog.discover()
        matches = tuple(item for item in view.skills if item.skill_id == descriptor.skill_id)
        if not view.usable or matches != (descriptor,):
            raise SessionControllerError("skill_install_failed")
        return descriptor
    except SkillPackageError as exc:
        raise SessionControllerError(exc.code) from None
    finally:
        self._release_admission(admission)
```

Default the installer from `store.workspace / ".coding-agent" / "skills"`; require an injected installer's normalized `workspace_skill_root` to equal that exact catalog root.

- [ ] **Step 4: Run GREEN and controller regression**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests/test_session_controller.py tests/test_skill_packages.py tests/test_skills.py
```

Expected: PASS.

- [ ] **Step 5: Review checkpoint**

Confirm import does not start a worker, publish run events, modify session selection directly, or bypass `_reserve_admission`. Confirm unusable/duplicate preflight rejection performs zero writes and post-publication inconsistency preserves the published file. Do not commit.

---

### Task 4: Add the authenticated raw-zip REST boundary

**Files:**

- Modify: `src/coding_agent/web.py`
- Modify: `tests/web_support.py`
- Modify: `tests/test_web_api.py`

**Interfaces:**

- Consumes: `SessionController.import_skill_archive(bytes) -> SkillDescriptor`.
- Produces: `POST /api/v1/skills/import`, HTTP 201 public descriptor, and route-specific media policy.

- [ ] **Step 1: Extend the recording controller and write route RED tests**

Add `imported_skill` and `delete_result` fixtures only when each route needs them. For Task 27, add:

```python
def import_skill_archive(self, archive: bytes) -> SkillDescriptor:
    self._record("import_skill_archive", archive)
    return self.imported_skill
```

Test exact body limit, first byte over, empty body, missing/wrong media type, `Content-Encoding`, 201 projection, Bearer/Host/Origin, and absence of body/instruction/path in the response. Parameterize the import route's exact stable mapping: `invalid_skill_archive`/`unsafe_skill_archive` -> 400, `skill_catalog_unavailable`/`skill_already_exists`/`controller_busy` -> 409, and `skill_install_failed` -> 500. Preserve the bounded-body `skill_archive_too_large` -> 413 behavior and prove a non-import `skill_catalog_unavailable` response retains its existing status.

- [ ] **Step 2: Run RED**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests/test_web_api.py -k "skill_import or skill_archive"
```

Expected: FAIL with 404 or media-type mismatch.

- [ ] **Step 3: Make media policy route-specific**

Replace the global JSON-only check with one deterministic helper:

```python
def _required_media_type(method: str, path: str) -> str | None:
    if method == "POST" and path == "/api/v1/skills/import":
        return "application/zip"
    if method in {"POST", "PUT", "PATCH"}:
        return "application/json"
    return None
```

Reject a non-empty `Content-Encoding` for the import route. Keep `_BoundedMutationBody` as the 131,072-byte outer bound.

- [ ] **Step 4: Implement the async import route**

Use:

```python
@app.post("/api/v1/skills/import", status_code=201)
async def import_skill(request: Request) -> dict[str, object] | JSONResponse:
    archive = await request.body()
    if not archive:
        return _error_response("invalid_skill_archive", status_code=400)
    try:
        descriptor = controller.import_skill_archive(archive)
    except SessionControllerError as exc:
        status = _skill_import_error_status(exc.code)
        if status is None:
            raise
        return _error_response(exc.code, status_code=status)
    return _serialize_skill(descriptor)
```

Implement `def _skill_import_error_status(code: str) -> int | None` as the exact route-specific map locked in Step 1, returning `None` for codes that must continue through the existing global handler. Return the fixed error response directly when empty; do not pass a path or filename to the controller. Do not alter the global status of `skill_catalog_unavailable` used by existing non-import routes.

- [ ] **Step 5: Run GREEN and Web security regression**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests/test_web_api.py tests/test_web_auth.py tests/test_web_sse.py
```

Expected: PASS.

- [ ] **Step 6: Review checkpoint**

Confirm JSON routes still require `application/json`, the token never enters a URL/body/log, and archive bytes are absent from errors and repr. Do not commit.

---

### Task 5: Add Skill import and empty-state GUI behavior

**Files:**

- Modify: `src/coding_agent/web_static/index.html`
- Modify: `src/coding_agent/web_static/app.js`
- Modify: `src/coding_agent/web_static/styles.css`
- Modify: `tests/js/web_gui.test.mjs`
- Modify: `tests/test_web_gui.py`

**Interfaces:**

- Consumes: `POST /api/v1/skills/import`, existing `listSkills()` and `saveSkillSelection()`.
- Produces: `api.importSkillArchive(file)`, import controls, empty state, refresh, and auto-selection.

- [ ] **Step 1: Add API-client RED tests for raw bodies**

Assert the import request uses the exact route, Bearer header, `Content-Type: application/zip`, raw `Blob` identity as the body, no JSON serialization, and no retry after failure.

Expected request assertions:

```javascript
assert.equal(request.method, "POST");
assert.equal(request.url, "http://local.invalid/api/v1/skills/import");
assert.equal(request.headers.get("content-type"), "application/zip");
assert.equal(await request.arrayBuffer().then((b) => b.byteLength), archive.size);
```

- [ ] **Step 2: Add controller/UI RED tests**

Extend the DOM fixture with `skillImportButton`, `skillFileInput`,
`skillEmptyState`, and `skillImportStatus`. Test empty catalog visibility,
single-file selection, repeated-click suppression, active-run disabling,
successful refresh, draft auto-selection, idle-session auto-selection through
the existing PUT, stable failure text, and clearing the input so the same file
can be selected again.

- [ ] **Step 3: Run RED**

Run:

```powershell
node --test tests/js/web_gui.test.mjs
.\.venv\Scripts\python.exe -m pytest -q tests/test_web_gui.py
```

Expected: FAIL because the elements and client method are absent.

- [ ] **Step 4: Split JSON and raw request construction**

Keep one response parser but allow exact raw options:

```javascript
async function request(path, { method = "GET", json, rawBody, contentType } = {}) {
  const headers = new Headers({ Authorization: `Bearer ${accessToken}` });
  const init = { method, headers };
  if (json !== undefined) {
    headers.set("Content-Type", "application/json");
    init.body = JSON.stringify(json);
  } else if (rawBody !== undefined) {
    headers.set("Content-Type", contentType);
    init.body = rawBody;
  }
  // Existing fetch, JSON response parse, and stable WebClientError mapping.
}
```

Reject a call that supplies both `json` and `rawBody` locally.

- [ ] **Step 5: Implement accessible import controls and state transitions**

Add a visible button and hidden `<input type="file" accept=".zip,application/zip">`. On button activation, click the input. On change, require exactly one file, call `importSkillArchive`, refresh `listSkills`, append the ID in catalog order, use the existing selection PUT only for an idle selected session, and render text through `appendPlainText`/text nodes.

- [ ] **Step 6: Run GREEN**

Run:

```powershell
node --test tests/js/web_gui.test.mjs
.\.venv\Scripts\python.exe -m pytest -q tests/test_web_gui.py tests/test_web_api.py
```

Expected: PASS.

- [ ] **Step 7: Review checkpoint**

Inspect keyboard focus, disabled state, narrow layout, safe text sinks, and no external resource or browser storage. Do not commit.

---

### Task 6: Verify, document, review, and close Task 27

**Files:**

- Modify: `README.md`
- Modify: `README.txt`
- Modify: `docs/USAGE.md`
- Modify: `tests/test_docs.py`
- Modify: `TASKS.md`

**Interfaces:**

- Consumes: complete Task 27 behavior.
- Produces: documented import contract and Task 27 `已完成`; Task 28 remains `未开始` until the next task starts.

- [ ] **Step 1: Add documentation contract RED tests**

Require documentation to name `.zip`, current-workspace-only installation,
single `SKILL.md`, no overwrite, no executable content, 128 KiB archive cap,
65,536-byte Skill cap, and active-run restriction.

- [ ] **Step 2: Run RED, update docs, then GREEN**

Run before and after edits:

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests/test_docs.py tests/test_cli.py
```

Expected before: new documentation assertions FAIL. Expected after: PASS.

- [ ] **Step 3: Run Task 27 focused verification**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests/test_skills.py tests/test_skill_packages.py tests/test_session_controller.py tests/test_web_api.py tests/test_web_auth.py tests/test_web_gui.py
node --test tests/js/web_gui.test.mjs
```

Expected: PASS with exit code 0.

- [ ] **Step 4: Run the complete Python and Node.js regressions**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
node --test tests/js/web_gui.test.mjs
```

Expected: all collected Python and Node.js tests pass with exit code 0. Record
the actual pass/fail/skip/warning counts. Task 27 cannot be marked `已完成` from
the focused suite alone.

- [ ] **Step 5: Run dependency, safety, secret, and scope audits**

Run:

```powershell
rg -n "langchain|llamaindex|autogen|crewai|python-multipart" pyproject.toml src tests
rg -n "OPENAI_API_KEY|CHAT_COMPLETIONS_API_KEY" src/coding_agent/web.py src/coding_agent/skill_packages.py src/coding_agent/web_static
rg -n "extractall|extract\(|shutil\.unpack_archive|shell=True|subprocess" src/coding_agent/skill_packages.py
git diff --check
```

Expected: no prohibited dependency/framework, no archive-wide extraction, no secret handling in the feature, and diff check exit code 0.

- [ ] **Step 6: Request final Task 27 code review**

Use `superpowers:requesting-code-review` across the Task 27 diff. Resolve findings, rerun Steps 3–5, and record actual commands/results.

- [ ] **Step 7: Use verification-before-completion and update status**

Only after fresh evidence passes, change Task 27 from `进行中` to `已完成` and Task 28 from `未开始` to `进行中`. Do not commit.

---

### Task 7: Add immutable deletion manifests and transactional Store deletion

**Files:**

- Modify: `src/coding_agent/session_store.py`
- Modify: `tests/test_session_store.py`

**Interfaces:**

- Consumes: existing session/run tables and ID validation.
- Produces: `SessionDeletionManifest(session_id: str, run_ids: tuple[str, ...], audit_run_ids: tuple[str, ...])` and three `SessionStore` Protocol operations: `get_session_deletion_manifest(session_id) -> SessionDeletionManifest`, `session_exists(session_id) -> bool`, and `delete_session(manifest) -> None`.

- [ ] **Step 1: Add dataclass invariant RED tests**

Test exact tuple types, valid session ID, valid unique 32-hex run/audit IDs, stable order, duplicate rejection, privacy-safe repr, and the three public Protocol methods. Assert `SessionStore.__dict__` contains `get_session_deletion_manifest`, `session_exists`, and `delete_session`, then use `inspect.signature`/`typing.get_type_hints` to verify the signatures locked in the Interfaces block. Use:

```python
manifest = SessionDeletionManifest(
    session_id=SESSION_ID,
    run_ids=(RUN_ID,),
    audit_run_ids=(AUDIT_ID,),
)
assert manifest.audit_run_ids == (AUDIT_ID,)
assert "workspace" not in repr(manifest)
```

- [ ] **Step 2: Add real-database manifest and deletion RED tests**

Create two sessions with multiple terminal runs, selections, snapshots, and events. Assert manifest ordering by run ordinal, non-null audit IDs only, complete deletion of the target's dependent rows, preservation of the other session, and `session_exists` true/false behavior.

- [ ] **Step 3: Run RED**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests/test_session_store.py -k "deletion_manifest or delete_session or session_exists"
```

Expected: FAIL because the types and methods do not exist.

- [ ] **Step 4: Implement manifest reads**

Within one connection, select the session and runs ordered by ordinal. Validate every run ID and non-null audit ID. Return immutable tuples and never include `final_report.log_path`.

Add all three methods to the public `SessionStore` Protocol before implementing the concrete methods. Implement `session_exists()` as an exact primary-key existence query that validates input and maps SQLite failures through existing store errors. The Task 9 fake store must call these public names and must not reach into `SQLiteSessionStore` private methods.

- [ ] **Step 5: Implement explicit transactional deletion**

Use `BEGIN IMMEDIATE`, reread the manifest, require exact equality and idle/no-active state, compute expected row counts before mutation, then execute exact parameterized statements in the approved order. Require each cursor row count to equal its preselected count and require the final session delete row count to equal one.

The implementation shape is:

```python
current = self._read_deletion_manifest(connection, manifest.session_id)
if current != manifest:
    raise SessionStoreError("invalid_session_state")
connection.execute("DELETE FROM session_events WHERE session_id = ?", (manifest.session_id,))
# Delete snapshots using exact validated run IDs, then runs, selections, session.
connection.commit()
```

Avoid an empty `IN ()`; skip the snapshot statement when `run_ids` is empty.

- [ ] **Step 6: Add rollback and stale-manifest RED tests**

Inject a trigger or connection fault after child deletion, then assert rollback restores every row. Also mutate the manifest-relevant data between read and delete and assert `invalid_session_state` with no row loss.

- [ ] **Step 7: Run GREEN and migration regression**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests/test_session_store.py tests/test_session.py
```

Expected: PASS; schema version remains unchanged.

- [ ] **Step 8: Request Store code review**

Use `superpowers:requesting-code-review` for the manifest and deletion transaction. Resolve findings and rerun Step 7. Do not commit.

---

### Task 8: Forget only deleted retained event projections

**Files:**

- Modify: `src/coding_agent/session_events.py`
- Modify: `tests/test_session_events.py`

**Interfaces:**

- Consumes: validated tuple of deleted run IDs.
- Produces: `SessionEventHub.forget_runs(run_ids: tuple[str, ...]) -> bool`.

- [ ] **Step 1: Add exact forgetting RED tests**

Begin and finish a retained run, then assert unrelated IDs return false and preserve reads, while the matching ID returns true and subsequent read/wait raises the existing not-found lookup. Reject list input, invalid IDs, and duplicates.

- [ ] **Step 2: Run RED**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests/test_session_events.py -k "forget_runs"
```

Expected: FAIL because `forget_runs` is absent.

- [ ] **Step 3: Implement locked exact clearing**

Under the hub condition lock, clear exactly the six state items that exist on
the current implementation: set `_session_id` and `_run_id` to `None`, clear
`_events` and `_lifecycle_updates`, set `_retained_bytes` to `0`, and set
`_next_sequence` to `1`. There is no terminal-marker field; do not add or write
one. Perform this clearing only when the current retained run ID is in the
validated tuple, then notify waiters and return whether a projection was
forgotten.

- [ ] **Step 4: Run GREEN**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests/test_session_events.py tests/test_web_sse.py
```

Expected: PASS.

- [ ] **Step 5: Review checkpoint**

Confirm unrelated run IDs and an empty tuple do not change state and no persisted session row is touched. Do not commit.

---

### Task 9: Implement reversible audit-log staging and startup recovery

**Files:**

- Create: `src/coding_agent/session_deletion.py`
- Create: `tests/test_session_deletion.py`

**Interfaces:**

- Consumes: `SessionStore.get_session_deletion_manifest`, `delete_session`, `session_exists`, exact workspace path.
- Produces: `SessionDeletionResult(session_id, run_ids, cleanup_pending)`, `SessionDeletionError(code)`, and `SessionDeletionService(workspace, store, *, operation_id_factory=uuid4_hex)` with read-only `workspace: Path` and `store: SessionStore` properties plus `delete()/recover_pending()`.

- [ ] **Step 1: Add result/error/path invariant RED tests**

Test exact dataclass types, hidden run IDs in repr, stable-code error repr, read-only workspace/store identity (`service.store is store`), 32-hex operation IDs, and audit targets derived only from IDs:

```python
assert service._audit_path(AUDIT_ID) == (
    workspace / ".coding-agent" / "logs" / f"{AUDIT_ID}.jsonl"
)
```

- [ ] **Step 2: Add happy deletion and missing-log RED tests**

Use a real `SQLiteSessionStore`, create exact audit files plus an unrelated JSONL, delete the target, and assert target database rows/logs/staging are gone while the unrelated file remains. A missing target log must still permit database deletion.

- [ ] **Step 3: Run RED**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests/test_session_deletion.py -k "delete or missing_log"
```

Expected: FAIL because the module is absent.

- [ ] **Step 4: Implement exact path and bounded manifest primitives**

Use constants for `.coding-agent`, `logs`, `deletion-staging`, `manifest.json`, and a small fixed manifest byte cap. Serialize canonical JSON with exactly:

```json
{
  "schema_version": 1,
  "operation_id": "<32 hex>",
  "session_id": "<validated id>",
  "audit_run_ids": ["<32 hex>"],
  "staged_audit_run_ids": ["<32 hex>"]
}
```

Reject extra/missing fields, wrong types/order/duplicates, invalid IDs, oversize, non-UTF-8, and noncanonical unsafe paths. During operation preparation, validate every exact audit source and compute `staged_audit_run_ids` as the stable subset whose regular files currently exist. Write `manifest.tmp` with exclusive create, flush, close, then rename to `manifest.json` before moving any recorded log. The published subset is immutable for the operation.

- [ ] **Step 5: Implement reversible delete orchestration**

Follow this state order exactly:

```python
manifest = store.get_session_deletion_manifest(session_id)
operation = self._prepare_operation(manifest)
try:
    self._stage_existing_logs(operation)
    store.delete_session(manifest)
except Exception:
    self._restore_logs_without_overwrite(operation)
    self._remove_empty_operation(operation)
    raise
cleanup_pending = not self._finish_cleanup(operation)
return SessionDeletionResult(session_id, manifest.run_ids, cleanup_pending)
```

Catch ordinary expected store/filesystem exceptions and translate them to stable codes without embedding exception text. Never catch `BaseException` for destructive recovery. If restore itself fails, raise `session_deletion_recovery_failed` and preserve the staging directory.

- [ ] **Step 6: Add failure-window RED tests**

Inject failures before manifest publication, after one log move, during database deletion, during restoration, after database commit, and during final staged-file deletion. Assert pre-commit failures preserve the session and restore logs; post-commit cleanup failure returns `cleanup_pending=True` with logs absent from the public logs directory.

- [ ] **Step 7: Add path-safety RED tests**

Cover reparse/symlink workspace internal directory, logs root, staging root, operation directory, manifest, audit file, staged file, non-regular types, restore collision, malformed ID, and unrelated files. On Windows privilege limitations, retain pure metadata-policy tests in addition to any platform-specific link test.

- [ ] **Step 8: Implement `recover_pending()` and crash-window tests**

Scan only immediate operation directories under the exact validated staging root. Each entry name must match the operation ID grammar. For a valid manifest, call `store.session_exists(session_id)`:

- true: for each `staged_audit_run_ids` entry, restore the staged log without overwrite; if the staged file is absent, require its exact public log to exist as proof that the move had not happened; then remove the manifest/empty directory;
- false: evaluate each `staged_audit_run_ids` entry by its exact staged/public pair. If staged exists and public does not, delete the staged file. If both are absent, accept that cleanup for this ID already completed. If public exists while staged is absent, fail closed; if both exist, also fail closed. After all entries are either deleted or already absent, remove the manifest and empty operation directory.

An empty valid operation directory without a manifest may be removed. Any other missing/malformed/unsafe case raises `session_deletion_recovery_failed` without deleting contents.

Test recovery before moves, after partial moves, before DB deletion, after DB commit, and after partial cleanup. The post-commit partial-cleanup test must include one ID for which both public and staged files are already absent and prove recovery succeeds, plus a separate public-present/staged-missing case that raises `session_deletion_recovery_failed` without deleting the public file or manifest.

- [ ] **Step 9: Run GREEN and path regression**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests/test_session_deletion.py tests/test_session_store.py tests/test_path_safety.py
```

Expected: PASS.

- [ ] **Step 10: Request deletion-service code review**

Use `superpowers:requesting-code-review` with special attention to destructive target resolution, crash windows, restoration, and no-glob guarantees. Resolve findings and rerun Step 9. Do not commit.

---

### Task 10: Wire deletion recovery and deletion through the controller

**Files:**

- Modify: `src/coding_agent/session_controller.py`
- Modify: `tests/test_session_controller.py`

**Interfaces:**

- Consumes: `SessionDeletionService.workspace/store/recover_pending/delete`, `SessionDeletionResult.run_ids`, and `SessionEventHub.forget_runs`.
- Produces: `SessionDeletionServiceFactory = Callable[[Path, SessionStore], SessionDeletionService]`, constructor injection `session_deletion: SessionDeletionService | None = None`, `SessionController.open(..., session_deletion_factory: SessionDeletionServiceFactory = default_session_deletion_service_factory)`, and `SessionController.delete_session(session_id) -> SessionDeletionResult`.

- [ ] **Step 1: Add startup recovery and admission RED tests**

Test default service composition and a recording `session_deletion_factory`. Prove `open()` calls the factory exactly once with the normalized requested workspace and the exact internally created `SQLiteSessionStore` object, and prove the controller stores that same returned service. Add factories returning a service bound to a different store object or workspace and assert fail-closed `invalid_session_state` plus lease closure. Also test successful open recovery, recovery failure closing the lease and surfacing `session_deletion_recovery_failed`, successful delete, event forgetting, `controller_busy`, active run, closed/degraded states, service failure translation, and admission release.

- [ ] **Step 2: Run RED**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests/test_session_controller.py -k "delete_session or deletion_recovery or session_deletion"
```

Expected: FAIL because the dependency and method are absent.

- [ ] **Step 3: Implement startup ordering**

Define the factory boundary exactly:

```python
SessionDeletionServiceFactory = Callable[
    [Path, SessionStore], SessionDeletionService
]


def default_session_deletion_service_factory(
    workspace: Path,
    store: SessionStore,
) -> SessionDeletionService:
    return SessionDeletionService(workspace, store)
```

In `SessionController.open()`, acquire the workspace lease, create and
initialize/recover the existing store, then call
`session_deletion_factory(store.workspace, store)`. Before recovery, require
`service.store is store` and require the normalized identity of
`service.workspace` to equal the normalized identity of `store.workspace`.
Pass that exact returned service into the controller, call
`service.recover_pending()`, and only then return an available controller. A
factory exception, identity mismatch, or recovery failure closes the lease and
propagates the locked stable controller error without opening a second store.

- [ ] **Step 4: Implement deletion admission**

Use:

```python
def delete_session(self, session_id: str) -> SessionDeletionResult:
    admission = self._reserve_admission()
    try:
        session = self._store.get_session(session_id)
        if session.status is not SessionStatus.IDLE:
            raise SessionControllerError("invalid_session_state")
        result = self._session_deletion.delete(session_id)
        self._event_hub.forget_runs(result.run_ids)
        if self._event_run_id in result.run_ids:
            self._event_run_id = None
        return result
    finally:
        self._release_admission(admission)
```

Translate store/deletion errors through stable codes and never report deletion before the service returns a durable result.

- [ ] **Step 5: Run GREEN and concurrency regression**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests/test_session_controller.py tests/test_session_deletion.py tests/test_session_events.py
```

Expected: PASS.

- [ ] **Step 6: Review checkpoint**

Confirm recovery occurs before admission, delete never runs concurrently with a worker, and a deleted retained run cannot pass `read_updates`. Do not commit.

---

### Task 11: Add the authenticated session DELETE REST contract

**Files:**

- Modify: `src/coding_agent/web.py`
- Modify: `tests/web_support.py`
- Modify: `tests/test_web_api.py`

**Interfaces:**

- Consumes: `SessionController.delete_session(session_id) -> SessionDeletionResult`.
- Produces: `DELETE /api/v1/sessions/{session_id}` success and warning projections.

- [ ] **Step 1: Extend the recording controller and write RED tests**

Add:

```python
def delete_session(self, session_id: str) -> SessionDeletionResult:
    self._record("delete_session", session_id)
    return self.delete_result
```

Test bodyless authenticated success, exact session ID delegation, no JSON media requirement, body rejection, normal success, cleanup-pending warning, missing session 404, state/busy 409, storage/recovery 503, and no run IDs/path/staging text in the response.

- [ ] **Step 2: Run RED**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests/test_web_api.py -k "delete_session"
```

Expected: FAIL with 404.

- [ ] **Step 3: Add DELETE to body-boundary policy without JSON coercion**

Extend `_MUTATION_METHODS` to include DELETE so a non-empty oversized body is still bounded, but make `_required_media_type()` return `None`. In the route reject any non-empty body with `invalid_request` before controller delegation.

- [ ] **Step 4: Implement exact serialization**

Return:

```python
payload = {
    "session_id": result.session_id,
    "deleted": True,
    "cleanup_pending": result.cleanup_pending,
}
if result.cleanup_pending:
    payload["warning_code"] = "session_log_cleanup_pending"
return payload
```

Never serialize `result.run_ids`.

- [ ] **Step 5: Run GREEN and REST regression**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests/test_web_api.py tests/test_web_auth.py tests/test_web_sse.py
```

Expected: PASS.

- [ ] **Step 6: Review checkpoint**

Confirm DELETE still requires Bearer/Host/Origin, accepts no body, and emits no sensitive path or OS error. Do not commit.

---

### Task 12: Add confirmed per-session deletion to the GUI

**Files:**

- Modify: `src/coding_agent/web_static/index.html`
- Modify: `src/coding_agent/web_static/app.js`
- Modify: `src/coding_agent/web_static/styles.css`
- Modify: `tests/js/web_gui.test.mjs`
- Modify: `tests/test_web_gui.py`

**Interfaces:**

- Consumes: `DELETE /api/v1/sessions/{session_id}`.
- Produces: `api.deleteSession(sessionId)`, title confirmation, deterministic selection, and cleanup warning.

- [ ] **Step 1: Add API-client DELETE RED tests**

Assert exact URL encoding, DELETE method, Bearer header, no body, no Content-Type, successful payload, and stable no-retry failure.

- [ ] **Step 2: Add GUI deletion RED tests**

Update the session-row fixture to include an independent delete button. Inject `confirmDelete` into `createUiController` so tests never depend on a real browser dialog. Cover:

- confirmation receives the exact plain session title;
- false confirmation sends no request;
- true confirmation sends one request and suppresses repeats;
- active/cancelling state disables every delete button;
- deleting an unselected row preserves current selection;
- deleting the selected row chooses its next sibling, else previous sibling;
- deleting the last row enters the new-session empty state;
- API failure preserves the row and selection;
- cleanup pending shows only the fixed local warning.

- [ ] **Step 3: Run RED**

Run:

```powershell
node --test tests/js/web_gui.test.mjs
.\.venv\Scripts\python.exe -m pytest -q tests/test_web_gui.py
```

Expected: FAIL because the API and controls are absent.

- [ ] **Step 4: Implement the client and state algorithm**

Add bodyless `deleteSession`. Before mutation capture the target index and whether it is selected. After success remove exactly the matching ID. If selected, choose `sessions[index]` after removal, otherwise `sessions[index - 1]`; if neither exists, clear selected session/run/provisional state and render the empty state. If unselected, do not reload the current session.

- [ ] **Step 5: Implement safe confirmation wiring**

Pass `confirmDelete` from `startBrowserApplication` as a bound wrapper around `window.confirm`. Build confirmation text from a fixed prefix plus the title, and never inject it through HTML. Put `data-delete-session-id` only on the delete control and keep row-selection event delegation separate.

- [ ] **Step 6: Run GREEN**

Run:

```powershell
node --test tests/js/web_gui.test.mjs
.\.venv\Scripts\python.exe -m pytest -q tests/test_web_gui.py tests/test_web_api.py
```

Expected: PASS.

- [ ] **Step 7: Review checkpoint**

Inspect keyboard accessibility, focus after selected deletion, narrow layout, safe text sinks, and accidental row-selection propagation. Do not commit.

---

### Task 13: Document, verify, review, and close Task 28

**Files:**

- Modify: `README.md`
- Modify: `README.txt`
- Modify: `docs/USAGE.md`
- Modify: `tests/test_docs.py`
- Modify: `TASKS.md`

**Interfaces:**

- Consumes: complete Task 28 behavior and completed Task 27.
- Produces: documented deletion/recovery contract and Task 28 `已完成`.

- [ ] **Step 1: Add documentation contract RED tests**

Require docs to state per-session confirmation, no bulk delete, active-run restriction, exact associated JSONL deletion, cleanup-pending behavior, startup recovery, no Agent deletion tool, and no arbitrary workspace deletion.

- [ ] **Step 2: Run RED, update docs, then GREEN**

Run before and after edits:

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests/test_docs.py tests/test_cli.py
```

Expected before: new assertions FAIL. Expected after: PASS.

- [ ] **Step 3: Run Task 28 focused verification**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests/test_session_store.py tests/test_session_deletion.py tests/test_session_events.py tests/test_session_controller.py tests/test_web_api.py tests/test_web_auth.py tests/test_web_sse.py tests/test_web_gui.py
node --test tests/js/web_gui.test.mjs
```

Expected: PASS with exit code 0.

- [ ] **Step 4: Run destructive-target and privacy audits**

Run:

```powershell
rg -n "glob|rglob|unlink|rmtree|Remove-Item|del |erase |log_path" src/coding_agent/session_deletion.py src/coding_agent/session_store.py
rg -n "absolute|workspace|manifest|staging|exception" tests/test_session_deletion.py
rg -n "innerHTML|outerHTML|insertAdjacentHTML|localStorage|sessionStorage" src/coding_agent/web_static
git diff --check
```

Expected: every filesystem deletion occurrence is an exact validated staging/log target explained by the implementation; no unsafe HTML/storage sink; diff check exit code 0.

- [ ] **Step 5: Run the complete offline regression**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
node --test tests/js/web_gui.test.mjs
```

Expected: all collected tests pass with exit code 0 and no network/API-key requirement.

- [ ] **Step 6: Run dependency, framework, secret, and status audits**

Run:

```powershell
rg -n "langchain|llamaindex|openai-agents|autogen|crewai|python-multipart" pyproject.toml src tests
rg -n "OPENAI_API_KEY|CHAT_COMPLETIONS_API_KEY" src/coding_agent/skill_packages.py src/coding_agent/session_deletion.py src/coding_agent/web_static
rg -n "^## 27\.|^## 28\.|`进行中`|`未开始`|`已完成`" TASKS.md
git status --short
```

Expected: no prohibited framework/new dependency, no credentials in new feature files, and only Task 28 remains `进行中` before the final status edit.

- [ ] **Step 7: Request final combined code review**

Use `superpowers:requesting-code-review` over all Task 27/28 production and test changes. Resolve findings and rerun Steps 3–6.

- [ ] **Step 8: Use verification-before-completion and update Task 28**

After fresh verification evidence, change Task 28 from `进行中` to `已完成`. Report every executed command and real exit code. Do not commit or push.

---

## Execution Gate

The user approved this design and plan in the current execution turn. Execute
it inline in the current task with `superpowers:executing-plans`; no additional
execution-mode choice and no unavailable sub-skill are prerequisites.
User-authorized read-only review subagents may support the explicit review
checkpoints, but all production changes remain sequential.

Do not create a worktree or begin Task 27 while Task 26 is incomplete. The
current approval does not bypass that prerequisite, the per-task verification
gates, or the prohibition on commit/push without separate authorization.

# Multi-Skill Workflow and Output-Limit Recovery Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Keep multiple development Skills selected together while making their stage handoff explicit, and recover once from a truncated main-model response with a larger, tightly bounded follow-up request.

**Architecture:** `RunInstructionBuilder` remains the single immutable instruction composition boundary and appends an authoritative, provider-neutral coordination section after selected Skill text. `AgentRunner` keeps its existing two-strike output-limit termination rule, but the sole recovery request is the only main request allowed to use 32,768 output tokens and receives a final, privacy-safe instruction requiring one complete bounded action. No provider SDK type, workflow state machine, new tool, dependency, or persisted phase is introduced.

**Tech Stack:** Python 3.11+, standard library, pytest, existing provider-neutral message and Agent interfaces.

**Spec:** `DESIGN.md`

## Global Constraints

- Work directly in the current main workspace as explicitly authorized by the user; do not create a branch or worktree.
- Do not stage, commit, push, pull, fetch, access a real provider, or read a real API key.
- Preserve simultaneous Skill selection and the existing immutable per-run Skill snapshot.
- Preserve `ModelClient.complete(ModelRequest) -> ModelResponse`, both provider adapters, tool safety, verification, continuation, and Task30 behavior.
- The normal main-request default remains 16,384 tokens; summaries remain explicitly capped at 4,096 tokens.
- Exactly one output-limit recovery request is allowed. A second consecutive output-limit error terminates as `model_output_limit` before a third request.
- Recovery instructions must not contain provider exception text, discarded partial output, Skill bodies, credentials, or local paths.
- No new dependency, Agent framework, public SDK type, persisted workflow phase, or automatic approval inference is added.

## File Map

- Modify `src/coding_agent/messages.py`: name the provider-neutral 16,384-token main default so `AgentRunner` does not duplicate it.
- Modify `src/coding_agent/instructions.py`: append a deterministic multi-Skill workflow coordination section after selected Skill instructions.
- Modify `src/coding_agent/agent.py`: strengthen the existing recovery instruction and use 32,768 tokens only for the single recovery request.
- Modify `tests/test_instructions.py`: verify deterministic coordination ordering and stage handoff language.
- Modify `tests/test_agent_loop.py`: verify normal/recovery token budgets, bounded recovery text, privacy, reset, and second-strike termination.
- Modify `tests/test_chat_completions_client.py`: reuse the named default while retaining the already-added real provider mapping regression.
- Modify `DESIGN.md`: record simultaneous Skill coordination and the one-shot 32,768-token recovery rule.
- Create this plan only; do not change `TASKS.md` because Task30 is already the sole in-progress task in the existing worktree.

### Task 1: Deterministic multi-Skill coordination

**Interfaces:**

- Consumes: `RunInstructionBuilder.build(workspace, *, skill_instructions, run_mode) -> RunInstructionSnapshot`.
- Produces: no signature change; snapshots with selected Skills end in one `## Skill workflow coordination` section.

- [ ] **Step 1: Write the failing instruction-composition test**

Add to `tests/test_instructions.py`:

```python
def test_selected_development_skills_receive_one_authoritative_handoff_section(
    tmp_path: Path,
) -> None:
    selected = "brainstorming rules\n\nwriting-plans rules\n\ntdd rules"

    snapshot = RunInstructionBuilder().build(
        tmp_path,
        skill_instructions=selected,
    )

    assert snapshot.text.count("## Skill workflow coordination") == 1
    assert snapshot.text.index("## Selected skill instructions") < snapshot.text.index(
        "## Skill workflow coordination"
    )
    coordination = snapshot.text.split("## Skill workflow coordination\n", 1)[1]
    assert "remain selected" in coordination
    assert "one primary process workflow" in coordination
    assert "approved design" in coordination
    assert "approved implementation plan" in coordination
    assert "Do not restart" in coordination
```

- [ ] **Step 2: Run RED**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest -p no:cacheprovider tests/test_instructions.py::test_selected_development_skills_receive_one_authoritative_handoff_section -q
```

Expected: exit code 1 because the coordination heading is absent.

- [ ] **Step 3: Implement the minimal composition change**

Add a private immutable coordination string to `instructions.py`. It must state that all selected Skills remain selected, exactly one process workflow is primary for the current stage, explicit approval hands off design to planning and planning to implementation, completed stages are not restarted, supporting safety constraints remain active, and ambiguity yields one concise question rather than speculative tools. Append it after selected Skill instructions only when Skill instructions exist.

- [ ] **Step 4: Run GREEN and instruction regression**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest -p no:cacheprovider tests/test_instructions.py -q
```

Expected: exit code 0 with every instruction test passing.

### Task 2: One-shot enlarged and bounded output recovery

**Interfaces:**

- Consumes: `ModelRequest.max_output_tokens`, `AgentState.consecutive_output_limit_errors`, existing `ModelOutputLimitError` handling.
- Produces: `DEFAULT_MODEL_MAX_OUTPUT_TOKENS = 16_384`; private recovery limit 32,768; no public method-signature change.

- [ ] **Step 1: Strengthen the existing recovery test before production changes**

Extend `test_output_limit_gets_one_temporary_small_tool_recovery_instruction` in `tests/test_agent_loop.py` with:

```python
assert client.requests[0].max_output_tokens == 16_384
assert client.requests[1].max_output_tokens == 32_768
assert recovery.endswith("Do not include prose together with a tool call.")
assert "exactly one complete action" in recovery
assert "12,000 characters" in recovery
assert "2,000 characters" in recovery
assert "private partial" not in recovery
```

Retain the existing assertions proving the instruction is temporary and absent from message history. Retain `test_second_consecutive_output_limit_stops_before_third_request` as the hard-stop regression.

- [ ] **Step 2: Run RED**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest -p no:cacheprovider tests/test_agent_loop.py::test_output_limit_gets_one_temporary_small_tool_recovery_instruction -q
```

Expected: exit code 1 because the recovery request still uses 16,384 and the stronger bounded contract is absent.

- [ ] **Step 3: Implement the minimal recovery change**

In `messages.py`, define `DEFAULT_MODEL_MAX_OUTPUT_TOKENS = 16_384` and use it as the `ModelRequest` default. In `agent.py`, import that constant, replace the recovery text with the exact bounded contract, and construct each main `ModelRequest` with 32,768 only when `consecutive_output_limit_errors == 1`; otherwise use the named 16,384 default. Keep the existing second-strike branch unchanged.

- [ ] **Step 4: Run GREEN and focused recovery regression**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest -p no:cacheprovider tests/test_agent_loop.py::test_output_limit_gets_one_temporary_small_tool_recovery_instruction tests/test_agent_loop.py::test_second_consecutive_output_limit_stops_before_third_request -q
```

Expected: exit code 0 with 2 passed.

- [ ] **Step 5: Run provider and Agent regression**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest -p no:cacheprovider tests/test_messages.py tests/test_instructions.py tests/test_agent_loop.py tests/test_chat_completions_client.py tests/test_chat_completions_streaming_client.py tests/test_openai_client.py tests/test_openai_streaming_client.py -q
```

Expected: exit code 0; custom per-request limits, summary 4,096 behavior, provider error parsing, discarded stream privacy, and existing termination rules remain green.

### Task 3: Design synchronization and final verification

**Interfaces:** No production interface changes.

- [ ] **Step 1: Update `DESIGN.md`**

Document that multiple selected staged Skills remain available while a final authoritative coordination section chooses one primary workflow from explicit approvals and conversation stage. Document normal 16,384 output, one 32,768 recovery request with one bounded complete action, and second-strike termination. Do not claim deterministic natural-language approval parsing or persisted workflow state.

- [ ] **Step 2: Run documentation and full tests**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest -p no:cacheprovider tests/test_docs.py -q
.\.venv\Scripts\python.exe -m pytest -p no:cacheprovider -q
```

Expected: both commands exit 0; report actual counts rather than estimates.

- [ ] **Step 3: Audit scope and safety**

Run:

```powershell
git diff --check
rg -n "OPENAI_API_KEY|CHAT_COMPLETIONS_API_KEY|Authorization:|sk-[A-Za-z0-9]" src tests DESIGN.md
git status --short --untracked-files=all
git diff --stat
```

Expected: whitespace check exits 0; no newly introduced credential value; no dependency, provider SDK, tool, safety, verification, or Task30 model-catalog change is introduced by this plan.

## Acceptance Matrix

| Requirement | Evidence |
| --- | --- |
| Three Skills remain selected together | instruction coordination test |
| One primary staged workflow | instruction coordination test |
| Explicit design and plan handoffs | instruction coordination test |
| Normal main output remains 16,384 | Agent recovery test and Chat mapping test |
| Sole recovery uses 32,768 | Agent recovery test |
| Recovery requests one bounded complete action | Agent recovery test |
| Discarded provider text remains private | existing and extended recovery tests |
| Second output limit stops before a third request | existing second-strike test |
| Summary remains 4,096 | context regression suite |
| Provider interfaces and streaming semantics remain compatible | both provider suites |
| No new dependency or remote access | diff and dependency review |

## Self-Review Result

- Every approved behavior maps to an executable test or audit command.
- Type and field names match the current repository interfaces.
- Normal and recovery token limits have explicit boundary values with no off-by-one ambiguity.
- The plan preserves simultaneous Skill selection without adding a second persisted workflow state machine.
- No placeholder, automatic commit, remote operation, Task30 scope change, or unsupported provider assumption is included.

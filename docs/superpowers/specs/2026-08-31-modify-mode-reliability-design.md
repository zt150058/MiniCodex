# Modify-Mode Reliability Design

## Status

Approved by the user's 2026-08-31 instruction to apply the recommended
architecture without another approval pause. This specification is a Task26
closure amendment and supersedes older Task25/Task26 rules only where it says
so explicitly.

## Problem statement

Three real modify-mode runs exposed different deterministic failures:

1. A knowledge question produced several equivalent text responses and ended
   as `no_progress`, because `ANSWERED` was restricted to `read_only` while a
   production modify run always owns an optional `VerificationGate`.
2. A successful `README.md` write ended as `changes_unverified`, because the
   first completion candidate with no model-selected evidence terminated
   immediately even when no mandatory `--verify` command existed.
3. A long C++ generation request returned three completed-but-unusable model
   responses and ended as `consecutive_model_errors`. A standard
   `finish_reason="length"` was classified as a generic malformed response and
   retried with the same request.

The repair must improve liveness without weakening workspace safety, executing
partial tool JSON, inventing verification evidence, or making `SUCCESS`
possible after a failed mandatory command.

## Locked decisions

### Capability mode is not intent classification

`RunMode.MODIFY` grants a tool capability; it does not require every valid run
to mutate. A non-empty final response with all of the following facts becomes
`AgentStatus.ANSWERED` in either run mode:

- `mutation_index == 0` and `modified_paths` is empty;
- no verification attempt or evidence exists;
- verification status is `NOT_RUN`;
- the response contains no tool calls.

`ANSWERED` remains distinct from `SUCCESS`. Its exit code is zero and it never
claims that code was changed or verified. The selected run mode remains in the
report and Session record. No prompt keyword classifier or silent mode switch
is introduced.

### Verification ladder

Modify-mode completion uses this deterministic order:

1. If a user supplied `--verify`, execute that exact authorized command. It is
   the mandatory gate and cannot fall back.
2. Without `--verify`, accept an already-recorded, fresh passing model-selected
   Python or Java verification result.
3. Without any current failed verification result, execute one local integrity
   validation over the exact first-seen `modified_paths` for the current
   `mutation_index`.
4. A current failed/timed-out/error verification result remains authoritative;
   local integrity validation must not overwrite it.

Local integrity validation is provider-neutral and deterministic. For every
changed path it reuses `PathGuard.existing_file`, rejects reparse/protected/
outside-workspace paths, reads at most the mutation tool's 524,288-byte limit,
and requires valid UTF-8. It additionally parses `.py` with `compile`, `.json`
with `json.loads`, and `.toml` with `tomllib.loads`. Other UTF-8 artifacts,
including Markdown, Java, C, and C++, receive integrity rather than behavioral
validation. The evidence uses `CommandSource.LOCAL_INTEGRITY`, command label
`builtin:validate_changed_files`, contains only normalized relative paths and
safe check names, and is fresh only at the current mutation index.

The integrity check consumes one verification/tool budget operation, produces
a normal `VerificationResult`, and can therefore enter `SUCCESS` only through
the existing freshness invariant. A user who needs build/test assurance must
provide `--verify` or have the model run an existing credible verifier. This
amendment does not authorize a compiler, package manager, shell, or arbitrary
executable.

### Output-limit and invalid-response recovery

`model.py` owns provider-neutral response failures:

- `InvalidModelResponseError`: a completed response cannot be safely parsed;
- `ModelOutputLimitError`: generation ended because the configured output
  limit was reached.

Both expose only fixed observation codes. Chat Completions maps
`finish_reason="length"` to `ModelOutputLimitError`; Responses maps
`status="incomplete"` plus `incomplete_details.reason ==
"max_output_tokens"` to the same type. No partial text or arguments are
committed or replayed.

On the first consecutive output-limit error, `AgentRunner` performs no tool
execution, records the error, and adds a temporary request instruction asking
for one small tool call at a time and one file per response. It then permits
one corrective main call, subject to every existing hard budget. A valid
response resets this recovery state. A second consecutive output-limit error
terminates as `model_output_limit` before a third request.

Other `InvalidModelResponseError` values terminate immediately as
`invalid_model_response`; repeating the identical local history cannot repair
a completed structurally invalid provider payload. Transient provider errors
retain their accepted adapter retry and Agent consecutive-error semantics.

### Streaming and privacy

Provisional deltas from an output-limited or malformed response remain
discarded. Confirmed assistant text is published only after a complete valid
`ModelResponse`. Recovery instructions are temporary request instructions,
not User/Assistant history, Session narrative, JSONL payload, or GUI content.
Reports, events, exceptions, and repr must not contain partial C++ source,
provider bodies, tool arguments, API keys, Authorization headers, continuation
payloads, or absolute workspace paths.

## Component changes

- `model.py`: provider-neutral error classes and stable codes.
- `chat_completions_client.py`, `openai_client.py`: exact output-limit mapping
  and invalid-response subclasses; SDK boundaries remain isolated.
- `state.py`, `agent.py`, `termination.py`: bounded output recovery, immediate
  invalid-response termination, and zero-mutation `ANSWERED`.
- `verification.py`, `safety.py`: local integrity evidence and source.
- `report.py`, `session.py`, `session_store.py`, `session_runtime.py`, audit and
  GUI contracts: allow modify-mode `ANSWERED` without changing its zero-fact
  invariant and render integrity evidence accurately.
- Instructions and public documentation: explain capability-mode answers,
  the verification ladder, output splitting, and the absence of a C++ command
  executor.

No database migration is required: run mode, agent status, and verification
source are stored as text, and `answered` already exists. Strict decoders and
tests must nevertheless be updated atomically.

## Acceptance

- A modify-mode knowledge response ends after one model call as `ANSWERED`.
- A successful README or source-file write with no mandatory verifier can pass
  fresh local integrity validation and end as `SUCCESS`.
- A failed model/user verification cannot be replaced by integrity evidence.
- A mandatory `--verify` failure remains `changes_unverified`/exit 1.
- A first output-limit error receives exactly one changed corrective request;
  a valid small tool call can continue, while a second limit terminates before
  a third request.
- A malformed completed response terminates after one request.
- Existing transient retry, Task8 safety, Task9 provider isolation, Task11
  freshness, streaming discard, Session ordering, and GUI safety tests remain
  green and offline.

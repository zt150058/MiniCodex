# Project instructions

This project implements a local coding agent from scratch.

## Hard constraints

- Do not use any agent framework or agent SDK, including LangChain,
  LlamaIndex, OpenAI Agents SDK, Claude Agent SDK, AutoGen, or CrewAI.
- Model-provider API clients and native tool-calling interfaces are allowed.
- Do not use server-hosted code execution or file tools.
- The agent loop, conversation history, context management, tool definitions,
  local tool execution, model-output parsing, termination conditions, and
  error handling must be implemented locally.
- Never store API keys in source code, tests, logs, documentation, commits,
  screenshots, or videos.
- Read credentials only from environment variables or ignored local
  configuration files.
- Restrict all filesystem operations to the configured workspace.
- Shell commands must have a timeout and output-size limit.

## Development workflow

- Use Superpowers brainstorming before introducing a new feature or changing
  existing behavior.
- Do not implement a design until the user explicitly approves it.
- Use writing-plans for multi-step implementation tasks.
- Use test-driven-development for production behavior and bug fixes.
- Use systematic-debugging for reproducible failures.
- Use verification-before-completion before claiming that work is complete,
  fixed, or passing.
- Use requesting-code-review after completing a core module.
- Do not dispatch subagents unless explicitly requested by the user.
- Do not use parallel agents for tightly coupled core modules.
- Do not create Git worktrees unless explicitly requested.
- Trivial documentation, formatting, and naming changes do not require a
  complete feature-development workflow.

## Coding rules

- Make small, reviewable changes.
- Complete one task or one coherent module at a time.
- Add or update tests for every behavioral change.
- Run relevant tests after modifications.
- Do not modify unrelated files.
- Prefer clear, explicit implementations over unnecessary abstractions.
- Prefer standard-library implementations where reasonable.
- Explain important design decisions before implementing them.
- Do not silently introduce new dependencies.
- Do not weaken tests merely to make them pass.

## Safety requirements

- Normalize and validate every filesystem path before use.
- Reject paths that resolve outside the configured workspace.
- Treat symbolic-link escapes as workspace violations.
- Run commands only inside the configured workspace.
- Reject destructive or prohibited commands.
- Capture command exit code, stdout, stderr, timeout status, and truncation
  status.
- Never rely only on model instructions for security enforcement.
- Enforce security restrictions in deterministic local code.

## Completion checklist

Before completing a task, verify:

- No prohibited agent framework or SDK was introduced.
- Core agent behavior remains implemented locally.
- Filesystem paths remain restricted to the workspace.
- Shell commands have timeout and output limits.
- Every loop has an explicit termination condition.
- Failure paths have appropriate tests.
- Secrets are not stored or exposed.
- Relevant tests were actually executed.
- Test commands and their real results are reported accurately.
- Verified facts are distinguished from assumptions.

## Design and approval gates

- Read `DESIGN.md` and `TASKS.md` before changing production behavior.
- `DESIGN.md` is the approved architectural source of truth.
- `TASKS.md` defines the implementation order and per-task acceptance criteria.
- Do not create production source code until the user approves `DESIGN.md`,
  `TASKS.md`, and `AGENTS.md`, then approves the detailed implementation plan.
- Do not invoke an implementation workflow while a required approval is
  pending.
- Work on one `TASKS.md` item at a time and keep its status accurate.
- If implementation reveals a design conflict, stop and return to
  brainstorming rather than silently changing the architecture.
- Do not commit, push, rewrite Git history, or operate on a remote repository
  unless the user explicitly authorizes that action.

## Project-specific implementation decisions

- Use Python and target Windows for the first version.
- Keep production code under `src/coding_agent/` and tests under `tests/`.
- Implement a one-shot CLI; do not add a chat REPL in the first version.
- Use an explicit synchronous agent loop, not an agent framework, independent
  planner, or multi-agent orchestration.
- Depend on the `ModelClient` protocol in core code. The first production
  adapter uses the official OpenAI Responses API; tests use `FakeModelClient`.
- Use `store=False` and manage active history and compaction locally. Do not
  use server-side conversation state as a substitute for local context logic.
- Use strict function-tool schemas, but validate every argument again locally.
- Execute tool calls sequentially in the first version.
- Every run has an explicit immutable `RunMode`; never infer authority from
  prompt text. `modify` remains the backward-compatible default.
- A `modify` run exposes exactly `list_directory`, `read_file`, `replace_text`,
  `write_file`, `run_command`, and `run_java_tests`.
- A `read_only` run exposes exactly `list_directory`, `read_file`, and the
  dedicated `inspect_git` tool. It must not construct mutation, generic
  command, Java, or verification tools.
- `ANSWERED` is valid only for a read-only run with non-empty final text, zero
  mutations, and no verification evidence. `SUCCESS` remains exclusive to a
  modification-capable run with fresh passing verification evidence.
- `write_file` may create a file but may not overwrite one. `replace_text`
  must require an exact expected match count. Do not add deletion or move
  tools in the first version.
- Parse commands into argument arrays and execute with `shell=False`.
- Do not expose PowerShell, `cmd.exe`, Bash, WSL, network commands, package
  installation, system administration, or destructive Git commands.
- `run_command` retains its Python and read-only Git allowlist. Java compiler
  and runtime commands are constructed only inside `run_java_tests`; model
  command strings cannot invoke them.
- Treat `.git/` and `.coding-agent/` as protected internal paths.
- Any successful file mutation must invalidate earlier verification evidence.
- If `--verify` is supplied, the agent may report success only after that exact
  command runs after the latest mutation and exits with code 0.
- Without `--verify`, require fresh evidence after the latest mutation from
  either a safe, credible `run_command` with `purpose="verification"` or an
  internally consistent `run_java_tests` call with `purpose="verification"`;
  inspection-only commands and Java calls with `purpose="test"` are not proof.
- After an ordinary decision checkpoint, count model responses that attempt
  reads and allow exactly one final batch for `standard` and two for `deep`.
  A duplicate-only read response closes reads immediately. Reject later reads
  with paired `agent_rejected:decision_required` results while still allowing
  legal mutation calls from the same model response, and give the model exactly
  one corrective response after the first decision attempt makes no progress.
- Model-facing verification guidance must name only the approved forms:
  `python <workspace-relative-file.py>`, `python -m pytest ...`,
  `python -m unittest ...` with `purpose="verification"`, and
  `run_java_tests` for Java. A rejected command may receive bounded safe
  correction, but local code must never rewrite or auto-execute it.
- Unverified mutations never succeed. If recovery ends without fresh passing
  evidence for the latest mutation, preserve the files and terminate as
  `changes_unverified`; do not claim rollback or `SUCCESS`.
- Every run has an immutable `BudgetProfile`. Keep `standard` aligned with
  `DESIGN.md`: 24 main model calls, 4 summary calls, 48 provider attempts,
  8 summary provider attempts, 80 tool calls, and 20 minutes. Keep `deep` at
  40 main calls, 6 summary calls, 80 provider attempts, 12 summary provider
  attempts, 140 tool calls, and 30 minutes. These are hard caps, not promised
  consumption. Summary failure must latch the deterministic local fallback;
  exploration limits must issue a decision checkpoint before `no_progress`.
- Write only redacted execution facts to JSONL. Never log hidden reasoning,
  authentication headers, environment dumps, or provider continuation payloads.
- Treat code executed from the workspace as trusted for the first version and
  state clearly that the project is not an operating-system sandbox.

## Dependency policy

- The approved production dependencies are `openai`, `fastapi`, and `uvicorn`.
- The approved test dependencies are `pytest` and `httpx`.
- `run_java_tests` introduces no new dependency and may not download a JDK.
- Any additional dependency requires an explicit design discussion and user
  approval before it is introduced.
- Never install a dependency merely to avoid implementing required core agent
  logic locally.

## Test and reporting rules

- Default automated tests must not require network access or a real API key.
- Use `FakeModelClient` for deterministic agent-loop tests.
- Test the OpenAI adapter with fake SDK responses; keep live API checks
  separate and explicitly opt-in.
- Test success and failure paths for every security rule, termination rule, and
  verification invariant.
- A model statement that work is complete is not proof. Report only local
  execution evidence and actual exit codes.
- Do not mark a `TASKS.md` item complete until its acceptance criteria and
  required tests have actually been satisfied.

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
import hashlib
import json
from pathlib import PurePosixPath, PureWindowsPath

from coding_agent.engine.budget import BudgetProfile
from coding_agent.engine.messages import ToolCall, ToolResult


class AgentPhase(StrEnum):
    DISCOVER = "discover"
    ACT = "act"
    VERIFY = "verify"
    FINISH = "finish"


class ProgressStrength(StrEnum):
    NONE = "none"
    WEAK = "weak"
    STRONG = "strong"


class ProgressAction(StrEnum):
    CONTINUE = "continue"
    CHECKPOINT = "checkpoint"
    DECISION_REQUIRED = "decision_required"
    STOP = "stop"


class ExplorationNovelty(StrEnum):
    NOT_READ = "not_read"
    NOVEL = "novel"
    DUPLICATE = "duplicate"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class ExplorationObservation:
    tool_name: str
    target_label: str | None = field(repr=False)
    request_fingerprint: str
    result_fingerprint: str
    mutation_epoch: int
    status: str


@dataclass(frozen=True, slots=True)
class ExplorationTurnSummary:
    attempted_reads: int
    novel_reads: int
    duplicate_reads: int
    failed_reads: int

    @property
    def duplicate_only(self) -> bool:
        return (
            self.attempted_reads > 0
            and self.duplicate_reads == self.attempted_reads
        )


_READ_TOOL_NAMES = frozenset({"list_directory", "read_file", "inspect_git"})


def _canonical_fingerprint(payload: object) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _safe_relative_label(value: object) -> str | None:
    if not isinstance(value, str) or not value or "\x00" in value:
        return None
    windows = PureWindowsPath(value)
    normalized = value.replace("\\", "/")
    posix = PurePosixPath(normalized)
    if windows.drive or windows.is_absolute() or posix.is_absolute():
        return None
    if any(part == ".." for part in posix.parts):
        return None
    safe = posix.as_posix()
    if safe in {"", ".."}:
        return None
    return safe


def _target_label(call: ToolCall, request_fingerprint: str) -> str | None:
    if call.name == "inspect_git":
        return f"inspect_git:{request_fingerprint[:12]}"
    path = _safe_relative_label(call.arguments.get("path"))
    if path is None:
        return None
    if call.name == "read_file":
        start = call.arguments.get("start_line")
        end = call.arguments.get("end_line")
        end_label = "null" if end is None else str(end)
        label = f"read_file:{path}:{start}-{end_label}"
    else:
        recursive = str(call.arguments.get("recursive")).lower()
        depth = call.arguments.get("max_depth")
        entries = call.arguments.get("max_entries")
        label = f"list_directory:{path}:{recursive}:{depth}:{entries}"
    return label[:256]


@dataclass(slots=True)
class ExplorationLedger:
    observations: list[ExplorationObservation] = field(
        default_factory=list,
        repr=False,
    )
    attempted_read_batches: int = 0
    novel_read_batches: int = 0
    duplicate_only_turns: int = 0
    context_compacted: bool = False
    _seen: set[tuple[int, str, str]] = field(
        default_factory=set,
        init=False,
        repr=False,
    )
    _turn_active: bool = field(default=False, init=False, repr=False)
    _attempted_reads: int = field(default=0, init=False, repr=False)
    _novel_reads: int = field(default=0, init=False, repr=False)
    _duplicate_reads: int = field(default=0, init=False, repr=False)
    _failed_reads: int = field(default=0, init=False, repr=False)
    _duplicate_result_count: int = field(default=0, init=False, repr=False)

    def begin_turn(self) -> None:
        if self._turn_active:
            raise RuntimeError("exploration turn is already active")
        self._turn_active = True
        self._attempted_reads = 0
        self._novel_reads = 0
        self._duplicate_reads = 0
        self._failed_reads = 0

    def observe(
        self,
        call: ToolCall,
        result: ToolResult,
        *,
        mutation_epoch: int,
    ) -> ExplorationNovelty:
        if not self._turn_active:
            raise RuntimeError("begin_turn must be called first")
        if not isinstance(call, ToolCall):
            raise TypeError("call must be ToolCall")
        if not isinstance(result, ToolResult):
            raise TypeError("result must be ToolResult")
        if type(mutation_epoch) is not int or mutation_epoch < 0:
            raise ValueError("mutation_epoch must be a non-negative integer")
        if call.name not in _READ_TOOL_NAMES:
            return ExplorationNovelty.NOT_READ

        request_fingerprint = _canonical_fingerprint(
            {"tool_name": call.name, "arguments": call.arguments}
        )
        metadata = result.metadata
        result_fingerprint = _canonical_fingerprint(
            {
                "status": result.status,
                "output": result.output,
                "error": result.error,
                "exit_code": metadata.exit_code,
                "timed_out": metadata.timed_out,
                "truncated": metadata.truncated,
                "duration_ms": metadata.duration_ms,
                "changed_paths": list(metadata.changed_paths),
            }
        )
        self._attempted_reads += 1
        if result.status != "ok":
            self._failed_reads += 1
            self.observations.append(
                ExplorationObservation(
                    tool_name=call.name,
                    target_label=None,
                    request_fingerprint=request_fingerprint,
                    result_fingerprint=result_fingerprint,
                    mutation_epoch=mutation_epoch,
                    status=result.status,
                )
            )
            return ExplorationNovelty.FAILED

        key = (mutation_epoch, request_fingerprint, result_fingerprint)
        novelty = (
            ExplorationNovelty.DUPLICATE
            if key in self._seen
            else ExplorationNovelty.NOVEL
        )
        self._seen.add(key)
        if novelty is ExplorationNovelty.NOVEL:
            self._novel_reads += 1
        else:
            self._duplicate_reads += 1
            self._duplicate_result_count += 1
        self.observations.append(
            ExplorationObservation(
                tool_name=call.name,
                target_label=_target_label(call, request_fingerprint),
                request_fingerprint=request_fingerprint,
                result_fingerprint=result_fingerprint,
                mutation_epoch=mutation_epoch,
                status=result.status,
            )
        )
        return novelty

    def finish_turn(self) -> ExplorationTurnSummary:
        if not self._turn_active:
            raise RuntimeError("no exploration turn is active")
        summary = ExplorationTurnSummary(
            attempted_reads=self._attempted_reads,
            novel_reads=self._novel_reads,
            duplicate_reads=self._duplicate_reads,
            failed_reads=self._failed_reads,
        )
        if summary.attempted_reads:
            self.attempted_read_batches += 1
        if summary.novel_reads:
            self.novel_read_batches += 1
        if summary.duplicate_only:
            self.duplicate_only_turns += 1
        self._turn_active = False
        return summary

    def mark_context_compacted(self) -> None:
        self.context_compacted = True

    def render_coverage(
        self,
        *,
        max_chars: int = 4096,
        force: bool = False,
    ) -> str | None:
        if type(max_chars) is not int or not 256 <= max_chars <= 12_000:
            raise ValueError("max_chars must be an integer from 256 to 12000")
        if not isinstance(force, bool):
            raise TypeError("force must be bool")
        if not self.context_compacted and not force:
            return None

        labels: list[str] = []
        seen_labels: set[str] = set()
        for observation in self.observations:
            label = observation.target_label
            if label is None or label in seen_labels:
                continue
            seen_labels.add(label)
            labels.append(label)

        def render(selected: list[str]) -> str:
            omitted = len(labels) - len(selected)
            lines = [
                "Exploration coverage:",
                f"- unique targets: {len(labels)}",
                f"- duplicate results: {self._duplicate_result_count}",
                f"- omitted targets: {omitted}",
                "- targets:",
            ]
            lines.extend(f"  - {label}" for label in selected)
            return "\n".join(lines)

        selected: list[str] = []
        for label in reversed(labels):
            candidate = [label, *selected]
            if len(render(candidate)) > max_chars:
                break
            selected = candidate
        return render(selected)


def _positive_integer(value: object, name: str) -> int:
    if type(value) is not int or value <= 0:
        raise ValueError(f"{name} must be a positive integer")
    return value


@dataclass(frozen=True, slots=True)
class ProgressLimits:
    main_turn_limit: int
    read_tool_limit: int
    idle_turn_limit: int
    post_checkpoint_turn_limit: int
    final_decision_remaining_calls: int = 4
    final_read_batch_limit: int = 1

    def __post_init__(self) -> None:
        for name in (
            "main_turn_limit",
            "read_tool_limit",
            "idle_turn_limit",
            "post_checkpoint_turn_limit",
            "final_decision_remaining_calls",
            "final_read_batch_limit",
        ):
            object.__setattr__(
                self,
                name,
                _positive_integer(getattr(self, name), name),
            )

    @classmethod
    def for_profile(cls, profile: BudgetProfile) -> ProgressLimits:
        if type(profile) is not BudgetProfile:
            raise TypeError("profile must be BudgetProfile")
        if profile is BudgetProfile.STANDARD:
            return cls(4, 12, 2, 2, 4, 1)
        return cls(6, 24, 3, 3, 4, 2)


@dataclass(frozen=True, slots=True)
class ProgressDecision:
    action: ProgressAction
    reason: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.action, ProgressAction):
            raise TypeError("action must be ProgressAction")
        if self.reason is not None and (
            not isinstance(self.reason, str) or not self.reason
        ):
            raise ValueError("reason must be a non-empty string or null")


@dataclass(slots=True)
class ProgressLedger:
    phase: AgentPhase = AgentPhase.DISCOVER
    epoch: int = 0
    main_turns_since_strong_progress: int = 0
    read_tools_since_strong_progress: int = 0
    idle_main_turns: int = 0
    checkpoint_active: bool = False
    post_checkpoint_main_turns: int = 0
    post_checkpoint_read_batches: int = 0
    decision_required: bool = False
    decision_attempts_without_progress: int = 0
    exploration: ExplorationLedger = field(default_factory=ExplorationLedger)
    _pending_duplicate_only: bool = field(default=False, init=False, repr=False)
    _turn_started_decision_required: bool = field(
        default=False,
        init=False,
        repr=False,
    )
    _turn_strength: ProgressStrength = field(
        default=ProgressStrength.NONE,
        init=False,
        repr=False,
    )
    _main_turn_active: bool = field(default=False, init=False, repr=False)
    _turn_read_tools: int = field(default=0, init=False, repr=False)
    _seen_observations: set[str] = field(
        default_factory=set,
        init=False,
        repr=False,
    )

    @staticmethod
    def _observation_fingerprint(call: ToolCall, result: ToolResult) -> str:
        metadata = result.metadata
        payload = {
            "tool_name": call.name,
            "arguments": call.arguments,
            "result": {
                "tool_name": result.tool_name,
                "status": result.status,
                "output": result.output,
                "error": result.error,
                "exit_code": metadata.exit_code,
                "timed_out": metadata.timed_out,
                "truncated": metadata.truncated,
                "changed_paths": list(metadata.changed_paths),
            },
        }
        encoded = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    def _record_strong_progress(self) -> None:
        if self._turn_strength is not ProgressStrength.STRONG:
            self.epoch += 1
        self._turn_strength = ProgressStrength.STRONG
        self.main_turns_since_strong_progress = 0
        self.read_tools_since_strong_progress = 0
        self.idle_main_turns = 0
        self.checkpoint_active = False
        self.post_checkpoint_main_turns = 0
        self.post_checkpoint_read_batches = 0
        self.decision_required = False
        self.decision_attempts_without_progress = 0
        self._pending_duplicate_only = False

    def activate_checkpoint(self) -> bool:
        if self.checkpoint_active:
            return False
        self.checkpoint_active = True
        self.post_checkpoint_main_turns = 0
        self.post_checkpoint_read_batches = 0
        self.decision_required = False
        self.decision_attempts_without_progress = 0
        self._pending_duplicate_only = False
        return True

    def begin_main_turn(self) -> None:
        if self._main_turn_active:
            raise RuntimeError("main turn is already active")
        self._main_turn_active = True
        self._turn_strength = ProgressStrength.NONE
        self._turn_read_tools = 0
        self._turn_started_decision_required = self.decision_required
        self.exploration.begin_turn()

    def observe_tool(
        self,
        call: ToolCall,
        result: ToolResult,
        *,
        mutation_advanced: bool,
        verification_advanced: bool,
        mutation_epoch: int = 0,
    ) -> ProgressStrength:
        if not self._main_turn_active:
            raise RuntimeError("begin_main_turn must be called first")
        if not isinstance(call, ToolCall):
            raise TypeError("call must be ToolCall")
        if not isinstance(result, ToolResult):
            raise TypeError("result must be ToolResult")
        if not isinstance(mutation_advanced, bool):
            raise TypeError("mutation_advanced must be bool")
        if not isinstance(verification_advanced, bool):
            raise TypeError("verification_advanced must be bool")
        if type(mutation_epoch) is not int or mutation_epoch < 0:
            raise ValueError("mutation_epoch must be a non-negative integer")
        exploration_novelty = self.exploration.observe(
            call,
            result,
            mutation_epoch=mutation_epoch,
        )
        if result.status != "ok":
            return ProgressStrength.NONE

        fingerprint = self._observation_fingerprint(call, result)
        novel = fingerprint not in self._seen_observations
        self._seen_observations.add(fingerprint)
        if mutation_advanced or verification_advanced:
            self._record_strong_progress()
            return ProgressStrength.STRONG
        if exploration_novelty is ExplorationNovelty.DUPLICATE or not novel:
            return ProgressStrength.NONE
        if self._turn_strength is ProgressStrength.NONE:
            self._turn_strength = ProgressStrength.WEAK
        if call.name in {"list_directory", "read_file", "inspect_git"}:
            self._turn_read_tools += 1
        return ProgressStrength.WEAK

    def observe_completion_candidate(self) -> None:
        if not self._main_turn_active:
            raise RuntimeError("begin_main_turn must be called first")
        self._record_strong_progress()

    def finish_main_turn(self) -> ProgressStrength:
        if not self._main_turn_active:
            raise RuntimeError("no main turn is active")
        strength = self._turn_strength
        exploration = self.exploration.finish_turn()
        if strength is ProgressStrength.WEAK:
            self.main_turns_since_strong_progress += 1
            self.read_tools_since_strong_progress += self._turn_read_tools
            self.idle_main_turns = 0
        elif strength is ProgressStrength.NONE:
            self.main_turns_since_strong_progress += 1
            self.idle_main_turns += 1
        checkpoint_was_active = self.checkpoint_active
        if self.checkpoint_active and strength is not ProgressStrength.STRONG:
            self.post_checkpoint_main_turns += 1
        if (
            checkpoint_was_active
            and strength is not ProgressStrength.STRONG
            and exploration.attempted_reads > 0
        ):
            self.post_checkpoint_read_batches += 1
        if exploration.duplicate_only and strength is not ProgressStrength.STRONG:
            if not self.checkpoint_active:
                self.activate_checkpoint()
            self.decision_required = True
            self._pending_duplicate_only = True
        if (
            self._turn_started_decision_required
            and strength is not ProgressStrength.STRONG
        ):
            self.decision_attempts_without_progress += 1
        self._main_turn_active = False
        self._turn_read_tools = 0
        self._turn_started_decision_required = False
        return strength

    def transition(self, phase: AgentPhase) -> bool:
        if not isinstance(phase, AgentPhase):
            raise TypeError("phase must be AgentPhase")
        if phase is self.phase:
            return False
        self.phase = phase
        self._record_strong_progress()
        return True

    def decide(
        self,
        limits: ProgressLimits,
        *,
        remaining_main_calls: int,
    ) -> ProgressDecision:
        if not isinstance(limits, ProgressLimits):
            raise TypeError("limits must be ProgressLimits")
        if type(remaining_main_calls) is not int or remaining_main_calls < 0:
            raise ValueError("remaining_main_calls must be a non-negative integer")
        if self.checkpoint_active:
            if self._pending_duplicate_only:
                self._pending_duplicate_only = False
                return ProgressDecision(
                    ProgressAction.DECISION_REQUIRED,
                    "duplicate_only_turn",
                )
            if self.decision_required:
                if self.decision_attempts_without_progress >= 2:
                    return ProgressDecision(ProgressAction.STOP, "no_progress")
                return ProgressDecision(ProgressAction.CONTINUE)
            if (
                self.post_checkpoint_main_turns
                >= limits.post_checkpoint_turn_limit
            ):
                return ProgressDecision(ProgressAction.STOP, "no_progress")
            if (
                self.post_checkpoint_read_batches
                >= limits.final_read_batch_limit
            ):
                self.decision_required = True
                return ProgressDecision(
                    ProgressAction.DECISION_REQUIRED,
                    "final_read_allowance_exhausted",
                )
            return ProgressDecision(ProgressAction.CONTINUE)
        if (
            self.main_turns_since_strong_progress >= limits.main_turn_limit
            or self.read_tools_since_strong_progress >= limits.read_tool_limit
            or self.idle_main_turns >= limits.idle_turn_limit
        ):
            self.activate_checkpoint()
            return ProgressDecision(
                ProgressAction.CHECKPOINT,
                "exploration_limit",
            )
        if remaining_main_calls <= limits.final_decision_remaining_calls:
            self.activate_checkpoint()
            return ProgressDecision(
                ProgressAction.CHECKPOINT,
                "final_call_reserve",
            )
        return ProgressDecision(ProgressAction.CONTINUE)


def render_execution_control(
    *,
    ledger: ProgressLedger,
    decision: ProgressDecision,
    profile: BudgetProfile,
    remaining_main_calls: int,
    remaining_tool_calls: int,
    verification_reserve: int,
    has_unverified_changes: bool = False,
) -> str:
    if not isinstance(ledger, ProgressLedger):
        raise TypeError("ledger must be ProgressLedger")
    if not isinstance(decision, ProgressDecision):
        raise TypeError("decision must be ProgressDecision")
    if type(profile) is not BudgetProfile:
        raise TypeError("profile must be BudgetProfile")
    if not isinstance(has_unverified_changes, bool):
        raise TypeError("has_unverified_changes must be bool")
    for name, value in (
        ("remaining_main_calls", remaining_main_calls),
        ("remaining_tool_calls", remaining_tool_calls),
        ("verification_reserve", verification_reserve),
    ):
        if type(value) is not int or value < 0:
            raise ValueError(f"{name} must be a non-negative integer")

    checkpoint = "active" if ledger.checkpoint_active else "inactive"
    limits = ProgressLimits.for_profile(profile)
    final_reads_remaining = max(
        0,
        limits.final_read_batch_limit - ledger.post_checkpoint_read_batches,
    )
    if ledger.decision_required:
        required_decision = "modify, answer, or report blocker"
        read_contract = "\n- read tools: further read tools will be rejected"
    else:
        required_decision = (
            "answer, act, inspect only named essentials, or report blocker"
            if ledger.checkpoint_active
            else "continue with the current phase"
        )
        read_contract = ""
    verification_contract = (
        "\n- unverified changes: active\n"
        "- required action: verify, repair failed verification, or report blocker\n"
        "- verification forms: python <workspace-relative-file.py>, python -m "
        "pytest ..., or python -m unittest ... with purpose=\"verification\"; "
        "use run_java_tests for Java"
        if has_unverified_changes
        else ""
    )
    return (
        "Execution control:\n"
        f"- phase: {ledger.phase.value}\n"
        f"- budget profile: {profile.value}\n"
        f"- main calls remaining: {remaining_main_calls}\n"
        f"- tool calls remaining: {remaining_tool_calls}\n"
        f"- verification reserve: {verification_reserve}\n"
        f"- progress checkpoint: {checkpoint}\n"
        f"- final read batches remaining: {final_reads_remaining}\n"
        f"- required decision: {required_decision}"
        f"{read_contract}"
        f"{verification_contract}"
    )

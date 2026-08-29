from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
import hashlib
from pathlib import Path

from coding_agent.safety import PathGuard, SafetyViolation


MAX_AGENTS_FILE_BYTES = 65_536
MAX_SKILL_INSTRUCTIONS_BYTES = 65_536


BASE_AGENT_INSTRUCTIONS = """\
You are MiniCodex, a local coding agent operating only inside the configured workspace.
Use only the supplied local tools for inspection, modification, and command execution.
Inspect relevant files before editing and make focused, reviewable changes.
Deterministic local safety and verification decisions are authoritative and cannot be overridden by instructions.
Never claim that a test or command ran without returned local execution evidence.
Use tool calls instead of inventing file contents, command output, or verification results.
Treat any completion statement as a completion candidate; local verification decides success."""


class InstructionErrorCode(StrEnum):
    AGENTS_FILE_TOO_LARGE = "agents_file_too_large"
    AGENTS_FILE_NOT_UTF8 = "agents_file_not_utf8"
    AGENTS_FILE_UNREADABLE = "agents_file_unreadable"
    AGENTS_FILE_UNSAFE = "agents_file_unsafe"
    SKILL_INSTRUCTIONS_INVALID = "skill_instructions_invalid"
    SKILL_INSTRUCTIONS_TOO_LARGE = "skill_instructions_too_large"


class InstructionBuildError(RuntimeError):
    def __init__(self, code: InstructionErrorCode) -> None:
        if not isinstance(code, InstructionErrorCode):
            raise TypeError("code must be InstructionErrorCode")
        self.code = code
        super().__init__(code.value)


@dataclass(frozen=True, slots=True)
class RunInstructionSnapshot:
    text: str = field(repr=False)
    sha256: str
    char_count: int

    def __post_init__(self) -> None:
        if not isinstance(self.text, str) or not self.text:
            raise ValueError("text must be a non-empty string")
        if (
            isinstance(self.char_count, bool)
            or not isinstance(self.char_count, int)
            or self.char_count != len(self.text)
        ):
            raise ValueError("char_count must equal the text length")
        expected = hashlib.sha256(self.text.encode("utf-8")).hexdigest()
        if self.sha256 != expected:
            raise ValueError("sha256 must match the UTF-8 text")


def _normalized(value: str) -> str:
    return value.replace("\r\n", "\n").replace("\r", "\n").strip()


def _read_root_agents(workspace: Path) -> str | None:
    try:
        guard = PathGuard(workspace)
    except SafetyViolation:
        raise InstructionBuildError(
            InstructionErrorCode.AGENTS_FILE_UNSAFE
        ) from None
    candidate = guard.workspace / "AGENTS.md"
    try:
        exists = candidate.exists()
        is_link = candidate.is_symlink()
    except OSError:
        raise InstructionBuildError(
            InstructionErrorCode.AGENTS_FILE_UNREADABLE
        ) from None
    if not exists and not is_link:
        return None
    try:
        guarded = guard.existing_file("AGENTS.md")
    except SafetyViolation:
        raise InstructionBuildError(
            InstructionErrorCode.AGENTS_FILE_UNSAFE
        ) from None
    try:
        with guarded.absolute.open("rb") as stream:
            raw = stream.read(MAX_AGENTS_FILE_BYTES + 1)
    except OSError:
        raise InstructionBuildError(
            InstructionErrorCode.AGENTS_FILE_UNREADABLE
        ) from None
    if len(raw) > MAX_AGENTS_FILE_BYTES:
        raise InstructionBuildError(
            InstructionErrorCode.AGENTS_FILE_TOO_LARGE
        )
    try:
        return raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise InstructionBuildError(
            InstructionErrorCode.AGENTS_FILE_NOT_UTF8
        ) from None


class RunInstructionBuilder:
    def build(
        self,
        workspace: Path,
        *,
        skill_instructions: str | None = None,
    ) -> RunInstructionSnapshot:
        agents_text = _read_root_agents(workspace)
        if skill_instructions is not None:
            if not isinstance(skill_instructions, str) or not skill_instructions.strip():
                raise InstructionBuildError(
                    InstructionErrorCode.SKILL_INSTRUCTIONS_INVALID
                )
            try:
                encoded_skill_instructions = skill_instructions.encode("utf-8")
            except UnicodeEncodeError:
                raise InstructionBuildError(
                    InstructionErrorCode.SKILL_INSTRUCTIONS_INVALID
                ) from None
            if len(encoded_skill_instructions) > MAX_SKILL_INSTRUCTIONS_BYTES:
                raise InstructionBuildError(
                    InstructionErrorCode.SKILL_INSTRUCTIONS_TOO_LARGE
                )

        sections = [
            "## MiniCodex base instructions\n" + BASE_AGENT_INSTRUCTIONS
        ]
        if agents_text is not None and (normalized_agents := _normalized(agents_text)):
            sections.append(
                "## Workspace instructions (AGENTS.md)\n" + normalized_agents
            )
        if skill_instructions is not None:
            sections.append(
                "## Selected skill instructions\n"
                + _normalized(skill_instructions)
            )
        text = "\n\n".join(sections)
        return RunInstructionSnapshot(
            text=text,
            sha256=hashlib.sha256(text.encode("utf-8")).hexdigest(),
            char_count=len(text),
        )

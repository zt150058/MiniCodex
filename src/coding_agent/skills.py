from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
import hashlib
import os
from pathlib import Path
import re
import stat
from typing import Mapping


MAX_SKILL_FILE_BYTES = 65_536
MAX_SELECTED_SKILL_BYTES = 65_536

_SKILL_ID_PATTERN = re.compile(r"[a-z0-9](?:[a-z0-9-]{0,62}[a-z0-9])?\Z")
_SHA256_PATTERN = re.compile(r"[0-9a-f]{64}\Z")
_METADATA_FIELDS = frozenset(("id", "name", "description"))


class SkillSource(StrEnum):
    USER = "user"
    WORKSPACE = "workspace"


def _require_exact_source(value: object) -> SkillSource:
    if type(value) is not SkillSource:
        raise TypeError("source must be SkillSource")
    return value


def _require_skill_id(value: object) -> str:
    if not isinstance(value, str) or _SKILL_ID_PATTERN.fullmatch(value) is None:
        raise ValueError("invalid skill id")
    return value


def _require_text(value: object, *, maximum: int) -> str:
    if not isinstance(value, str) or not value or len(value) > maximum:
        raise ValueError("invalid skill metadata")
    _validate_decoded_controls(value)
    if "\r" in value or "\n" in value:
        raise ValueError("invalid skill metadata")
    return value


def _require_sha256(value: object) -> str:
    if not isinstance(value, str) or _SHA256_PATTERN.fullmatch(value) is None:
        raise ValueError("invalid sha256")
    return value


def _require_positive_count(value: object) -> int:
    if type(value) is not int or value <= 0:
        raise ValueError("invalid character count")
    return value


@dataclass(frozen=True, slots=True)
class SkillDescriptor:
    skill_id: str
    name: str
    description: str
    source: SkillSource
    sha256: str
    char_count: int

    def __post_init__(self) -> None:
        _require_skill_id(self.skill_id)
        _require_text(self.name, maximum=80)
        _require_text(self.description, maximum=240)
        _require_exact_source(self.source)
        _require_sha256(self.sha256)
        _require_positive_count(self.char_count)


@dataclass(frozen=True, slots=True)
class SkillCatalogDiagnostic:
    code: str
    source: SkillSource
    entry_name: str

    def __post_init__(self) -> None:
        if not isinstance(self.code, str) or not self.code:
            raise ValueError("invalid diagnostic code")
        _require_exact_source(self.source)
        if not isinstance(self.entry_name, str) or not self.entry_name:
            raise ValueError("invalid diagnostic entry")


@dataclass(frozen=True, slots=True)
class SkillCatalogView:
    skills: tuple[SkillDescriptor, ...]
    diagnostics: tuple[SkillCatalogDiagnostic, ...]
    usable: bool

    def __post_init__(self) -> None:
        if type(self.skills) is not tuple or any(
            type(item) is not SkillDescriptor for item in self.skills
        ):
            raise TypeError("skills must be a tuple of SkillDescriptor")
        if type(self.diagnostics) is not tuple or any(
            type(item) is not SkillCatalogDiagnostic for item in self.diagnostics
        ):
            raise TypeError("diagnostics must be a tuple of SkillCatalogDiagnostic")
        if type(self.usable) is not bool:
            raise TypeError("usable must be bool")


@dataclass(frozen=True, slots=True)
class SkillInstructionSnapshot:
    descriptor: SkillDescriptor
    instructions: str = field(repr=False)

    def __post_init__(self) -> None:
        if type(self.descriptor) is not SkillDescriptor:
            raise TypeError("descriptor must be SkillDescriptor")
        if not isinstance(self.instructions, str) or not self.instructions:
            raise ValueError("instructions must be non-empty")
        encoded = self.instructions.encode("utf-8")
        if hashlib.sha256(encoded).hexdigest() != self.descriptor.sha256:
            raise ValueError("instruction hash mismatch")
        if len(self.instructions) != self.descriptor.char_count:
            raise ValueError("instruction character count mismatch")


@dataclass(frozen=True, slots=True)
class SkillInstructionBundle:
    items: tuple[SkillInstructionSnapshot, ...]
    text: str = field(repr=False)
    sha256: str
    char_count: int

    def __post_init__(self) -> None:
        if type(self.items) is not tuple or not self.items or any(
            type(item) is not SkillInstructionSnapshot for item in self.items
        ):
            raise TypeError("items must be a non-empty tuple of SkillInstructionSnapshot")
        if not isinstance(self.text, str) or not self.text:
            raise ValueError("text must be non-empty")
        _require_sha256(self.sha256)
        _require_positive_count(self.char_count)
        encoded = self.text.encode("utf-8")
        if hashlib.sha256(encoded).hexdigest() != self.sha256:
            raise ValueError("bundle hash mismatch")
        if len(self.text) != self.char_count:
            raise ValueError("bundle character count mismatch")


@dataclass(frozen=True, slots=True)
class RunSkillSnapshotMetadata:
    skill_id: str
    source: SkillSource
    sha256: str
    char_count: int

    def __post_init__(self) -> None:
        _require_skill_id(self.skill_id)
        _require_exact_source(self.source)
        _require_sha256(self.sha256)
        _require_positive_count(self.char_count)


class SkillCatalogError(RuntimeError):
    def __init__(self, code: str) -> None:
        if not isinstance(code, str) or not code:
            raise ValueError("invalid skill catalog error code")
        self.code = code
        super().__init__(code)

    def __repr__(self) -> str:
        return f"SkillCatalogError({self.code!r})"


class _EntryError(Exception):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True, slots=True)
class _SkillDefinition:
    descriptor: SkillDescriptor
    instructions: str = field(repr=False)


@dataclass(frozen=True, slots=True)
class _CatalogScan:
    definitions: tuple[_SkillDefinition, ...]
    diagnostics: tuple[SkillCatalogDiagnostic, ...]
    unavailable: bool
    conflicted: bool


def _validate_decoded_controls(value: str) -> None:
    for character in value:
        codepoint = ord(character)
        if codepoint == 0x7F or (codepoint < 0x20 and character not in "\t\r\n"):
            raise ValueError("invalid control character")


def _normalize_body(value: str) -> str:
    return value.replace("\r\n", "\n").replace("\r", "\n").strip()


def _is_reparse(metadata: os.stat_result) -> bool:
    attributes = getattr(metadata, "st_file_attributes", 0)
    return stat.S_ISLNK(metadata.st_mode) or bool(attributes & 0x400)


def _parse_skill_document(
    raw: bytes,
    source: SkillSource,
    entry_name: str,
) -> _SkillDefinition:
    if not isinstance(raw, bytes):
        raise TypeError("raw must be bytes")
    if len(raw) > MAX_SKILL_FILE_BYTES:
        raise _EntryError("skill_file_too_large")
    try:
        decoded = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise _EntryError("skill_file_not_utf8") from None
    try:
        _validate_decoded_controls(decoded)
    except ValueError:
        raise _EntryError("invalid_skill_instructions") from None
    normalized_text = decoded.replace("\r\n", "\n").replace("\r", "\n")
    lines = normalized_text.split("\n")
    if not lines or lines[0] != "---":
        raise _EntryError("invalid_skill_front_matter")
    try:
        closing = lines.index("---", 1)
    except ValueError:
        raise _EntryError("invalid_skill_front_matter") from None
    values: dict[str, str] = {}
    for line in lines[1:closing]:
        if ":" not in line:
            raise _EntryError("invalid_skill_front_matter")
        key, raw_value = line.split(":", 1)
        if key not in _METADATA_FIELDS or key in values:
            raise _EntryError("invalid_skill_front_matter")
        value = raw_value.strip()
        if not value:
            raise _EntryError("invalid_skill_metadata")
        values[key] = value
    if set(values) != _METADATA_FIELDS:
        raise _EntryError("invalid_skill_front_matter")
    if values["id"] != entry_name:
        raise _EntryError("skill_id_mismatch")
    body = _normalize_body("\n".join(lines[closing + 1 :]))
    if not body:
        raise _EntryError("empty_skill_instructions")
    encoded_body = body.encode("utf-8")
    try:
        descriptor = SkillDescriptor(
            skill_id=values["id"],
            name=values["name"],
            description=values["description"],
            source=source,
            sha256=hashlib.sha256(encoded_body).hexdigest(),
            char_count=len(body),
        )
    except (TypeError, ValueError):
        raise _EntryError("invalid_skill_metadata") from None
    return _SkillDefinition(descriptor=descriptor, instructions=body)


def _read_definition(
    path: Path,
    source: SkillSource,
    entry_name: str,
) -> _SkillDefinition:
    try:
        metadata = os.lstat(path)
        if _is_reparse(metadata) or not stat.S_ISREG(metadata.st_mode):
            raise _EntryError("unsafe_skill_path")
        with path.open("rb") as handle:
            raw = handle.read(MAX_SKILL_FILE_BYTES + 1)
    except FileNotFoundError:
        raise _EntryError("missing_skill_file") from None
    except OSError:
        raise _EntryError("missing_skill_file") from None
    if len(raw) > MAX_SKILL_FILE_BYTES:
        raise _EntryError("skill_file_too_large")
    return _parse_skill_document(raw, source, entry_name)


class SkillCatalog:
    def __init__(
        self,
        *,
        user_root: Path,
        workspace_root: Path,
    ) -> None:
        if not isinstance(user_root, Path) or not isinstance(workspace_root, Path):
            raise TypeError("catalog roots must be Path")
        self._user_root: Path | None = Path(os.path.abspath(user_root))
        self._workspace_root = Path(os.path.abspath(workspace_root))

    @classmethod
    def from_environment(
        cls,
        workspace: Path,
        *,
        environ: Mapping[str, str] | None = None,
    ) -> SkillCatalog:
        if not isinstance(workspace, Path):
            raise TypeError("workspace must be Path")
        workspace_root = Path(os.path.abspath(workspace))
        copied_environment = dict(os.environ if environ is None else environ)
        local_app_data = copied_environment.get("LOCALAPPDATA")
        if (
            isinstance(local_app_data, str)
            and local_app_data
            and local_app_data == local_app_data.strip()
            and Path(local_app_data).is_absolute()
        ):
            return cls(
                user_root=Path(local_app_data) / "MiniCodex" / "skills",
                workspace_root=workspace_root / ".coding-agent" / "skills",
            )
        catalog = cls.__new__(cls)
        catalog._user_root = None
        catalog._workspace_root = workspace_root / ".coding-agent" / "skills"
        return catalog

    @property
    def workspace_root(self) -> Path:
        return self._workspace_root

    def _scan(self) -> _CatalogScan:
        definitions: list[_SkillDefinition] = []
        diagnostics: list[SkillCatalogDiagnostic] = []
        candidate_sources: dict[str, list[SkillSource]] = {}
        unavailable = False
        for source, root in (
            (SkillSource.USER, self._user_root),
            (SkillSource.WORKSPACE, self._workspace_root),
        ):
            if root is None:
                diagnostics.append(
                    SkillCatalogDiagnostic(
                        code="catalog_root_unavailable",
                        source=source,
                        entry_name="<catalog>",
                    )
                )
                unavailable = True
                continue
            try:
                root_metadata = os.lstat(root)
            except FileNotFoundError:
                continue
            except OSError:
                diagnostics.append(
                    SkillCatalogDiagnostic(
                        code="catalog_root_unavailable",
                        source=source,
                        entry_name="<catalog>",
                    )
                )
                unavailable = True
                continue
            try:
                if _is_reparse(root_metadata) or not stat.S_ISDIR(
                    root_metadata.st_mode
                ):
                    raise NotADirectoryError
                entries = sorted(root.iterdir(), key=lambda item: item.name)
            except OSError:
                diagnostics.append(
                    SkillCatalogDiagnostic(
                        code="catalog_root_unavailable",
                        source=source,
                        entry_name="<catalog>",
                    )
                )
                unavailable = True
                continue
            for entry in entries:
                candidate_id = (
                    entry.name
                    if _SKILL_ID_PATTERN.fullmatch(entry.name) is not None
                    else None
                )
                try:
                    entry_metadata = os.lstat(entry)
                except OSError:
                    if candidate_id is not None:
                        candidate_sources.setdefault(candidate_id, []).append(source)
                        diagnostics.append(
                            SkillCatalogDiagnostic(
                                code="unsafe_skill_path",
                                source=source,
                                entry_name=candidate_id,
                            )
                        )
                    continue
                if _is_reparse(entry_metadata):
                    if candidate_id is not None:
                        candidate_sources.setdefault(candidate_id, []).append(source)
                    diagnostics.append(
                        SkillCatalogDiagnostic(
                            code="unsafe_skill_path",
                            source=source,
                            entry_name=entry.name,
                        )
                    )
                    continue
                if not stat.S_ISDIR(entry_metadata.st_mode):
                    continue
                if candidate_id is None:
                    diagnostics.append(
                        SkillCatalogDiagnostic(
                            code="invalid_entry_name",
                            source=source,
                            entry_name=entry.name,
                        )
                    )
                    continue
                candidate_sources.setdefault(candidate_id, []).append(source)
                try:
                    definition = _read_definition(
                        entry / "SKILL.md",
                        source,
                        entry.name,
                    )
                except _EntryError as exc:
                    diagnostics.append(
                        SkillCatalogDiagnostic(
                            code=exc.code,
                            source=source,
                            entry_name=entry.name,
                        )
                    )
                    continue
                definitions.append(definition)
        duplicate_ids = {
            skill_id
            for skill_id, sources in candidate_sources.items()
            if len(sources) > 1
        }
        if duplicate_ids:
            for skill_id in duplicate_ids:
                for source in candidate_sources[skill_id]:
                    diagnostics.append(
                        SkillCatalogDiagnostic(
                            code="duplicate_skill_id",
                            source=source,
                            entry_name=skill_id,
                        )
                    )
            definitions = [
                definition
                for definition in definitions
                if definition.descriptor.skill_id not in duplicate_ids
            ]
        return _CatalogScan(
            definitions=tuple(sorted(definitions, key=lambda item: item.descriptor.skill_id)),
            diagnostics=tuple(
                sorted(
                    diagnostics,
                    key=lambda item: (
                        item.source.value,
                        item.entry_name,
                        item.code,
                    ),
                )
            ),
            unavailable=unavailable,
            conflicted=bool(duplicate_ids),
        )

    def discover(self) -> SkillCatalogView:
        scan = self._scan()
        return SkillCatalogView(
            skills=tuple(item.descriptor for item in scan.definitions),
            diagnostics=scan.diagnostics,
            usable=not scan.unavailable and not scan.conflicted,
        )

    def resolve(
        self,
        skill_ids: tuple[str, ...],
    ) -> SkillInstructionBundle | None:
        if type(skill_ids) is not tuple:
            raise SkillCatalogError("invalid_skill_selection")
        if not skill_ids:
            return None
        if any(
            type(skill_id) is not str
            or _SKILL_ID_PATTERN.fullmatch(skill_id) is None
            for skill_id in skill_ids
        ):
            raise SkillCatalogError("invalid_skill_selection")
        if len(set(skill_ids)) != len(skill_ids):
            raise SkillCatalogError("duplicate_skill_selection")
        scan = self._scan()
        if scan.unavailable:
            raise SkillCatalogError("skill_catalog_unavailable")
        if scan.conflicted:
            raise SkillCatalogError("duplicate_skill_id")
        definitions = {
            item.descriptor.skill_id: item for item in scan.definitions
        }
        try:
            selected = tuple(definitions[skill_id] for skill_id in skill_ids)
        except KeyError:
            raise SkillCatalogError("selected_skill_unavailable") from None
        snapshots = tuple(
            SkillInstructionSnapshot(
                descriptor=item.descriptor,
                instructions=item.instructions,
            )
            for item in selected
        )
        text = "\n\n".join(
            f"### Skill: {item.descriptor.skill_id} — {item.descriptor.name}\n"
            f"{item.instructions}"
            for item in snapshots
        )
        encoded_text = text.encode("utf-8")
        if len(encoded_text) > MAX_SELECTED_SKILL_BYTES:
            raise SkillCatalogError("skill_selection_too_large")
        return SkillInstructionBundle(
            items=snapshots,
            text=text,
            sha256=hashlib.sha256(encoded_text).hexdigest(),
            char_count=len(text),
        )

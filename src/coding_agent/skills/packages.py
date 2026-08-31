from __future__ import annotations

from dataclasses import dataclass, field
import io
import os
from pathlib import Path
import re
import stat
from typing import Callable
from uuid import uuid4
import zipfile

from .catalog import (
    MAX_SKILL_FILE_BYTES,
    SkillDescriptor,
    SkillSource,
    _EntryError,
    _is_reparse,
    _parse_skill_document,
    _read_definition,
)


MAX_SKILL_ARCHIVE_BYTES = 131_072

_ALLOWED_ZIP_FLAGS = 0x0008 | 0x0800
_OPERATION_ID = re.compile(r"[0-9a-f]{32}\Z")
_EOCD_SIGNATURE = b"PK\x05\x06"
_DOS_DIRECTORY = 0x10
_DOS_DEVICE = 0x40
_DOS_REPARSE_POINT = 0x400
_ALLOWED_DOS_ATTRIBUTES = 0x01 | 0x02 | 0x04 | _DOS_DIRECTORY | 0x20


def _uuid4_hex() -> str:
    return uuid4().hex


class SkillPackageError(RuntimeError):
    def __init__(self, code: str) -> None:
        if not isinstance(code, str) or not code:
            raise ValueError("invalid skill package error code")
        self.code = code
        super().__init__(code)

    def __repr__(self) -> str:
        return f"SkillPackageError({self.code!r})"


@dataclass(frozen=True, slots=True)
class _ParsedPackage:
    descriptor: SkillDescriptor
    raw_definition: bytes = field(repr=False)


def _reject_unsafe_name(name: str) -> None:
    if not name or name.startswith(("/", "\\")) or "\\" in name or ":" in name:
        raise SkillPackageError("unsafe_skill_archive")
    if any(ord(character) < 0x20 or ord(character) == 0x7F for character in name):
        raise SkillPackageError("unsafe_skill_archive")
    parts = name.split("/")
    interior = parts[:-1] if parts[-1] == "" else parts
    if any(part in {"", ".", ".."} for part in interior):
        raise SkillPackageError("unsafe_skill_archive")


def _validate_external_type(info: zipfile.ZipInfo) -> None:
    dos_attributes = info.external_attr & 0xFFFF
    if dos_attributes & (_DOS_DEVICE | _DOS_REPARSE_POINT):
        raise SkillPackageError("unsafe_skill_archive")
    if info.create_system == 0:
        if dos_attributes & ~_ALLOWED_DOS_ATTRIBUTES:
            raise SkillPackageError("unsafe_skill_archive")
        if bool(dos_attributes & _DOS_DIRECTORY) != info.is_dir():
            raise SkillPackageError("unsafe_skill_archive")
        return
    if info.create_system != 3:
        return
    mode = (info.external_attr >> 16) & 0xFFFF
    kind = stat.S_IFMT(mode)
    allowed = {0, stat.S_IFDIR if info.is_dir() else stat.S_IFREG}
    if kind not in allowed:
        raise SkillPackageError("unsafe_skill_archive")


def _has_exact_eocd(archive: bytes) -> bool:
    position = archive.rfind(_EOCD_SIGNATURE)
    if position < 0 or position + 22 > len(archive):
        return False
    comment_size = int.from_bytes(archive[position + 20 : position + 22], "little")
    return position + 22 + comment_size == len(archive)


def _parse_package(archive: bytes) -> _ParsedPackage:
    if type(archive) is not bytes or not archive:
        raise SkillPackageError("invalid_skill_archive")
    if len(archive) > MAX_SKILL_ARCHIVE_BYTES:
        raise SkillPackageError("skill_archive_too_large")
    if not archive.startswith(b"PK\x03\x04") or not _has_exact_eocd(archive):
        raise SkillPackageError("invalid_skill_archive")
    try:
        with zipfile.ZipFile(io.BytesIO(archive), "r") as package:
            infos = package.infolist()
            raw_names: set[str] = set()
            directory_info: zipfile.ZipInfo | None = None
            file_info: zipfile.ZipInfo | None = None
            skill_id: str | None = None
            for info in infos:
                name = info.orig_filename
                _reject_unsafe_name(name)
                if name in raw_names:
                    raise SkillPackageError("invalid_skill_archive")
                raw_names.add(name)
                if info.flag_bits & 0x1:
                    raise SkillPackageError("unsafe_skill_archive")
                if info.flag_bits & ~_ALLOWED_ZIP_FLAGS:
                    raise SkillPackageError("invalid_skill_archive")
                if info.compress_type not in {zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED}:
                    raise SkillPackageError("invalid_skill_archive")
                if (
                    info.file_size < 0
                    or info.file_size > MAX_SKILL_FILE_BYTES
                    or info.compress_size < 0
                    or info.compress_size > MAX_SKILL_ARCHIVE_BYTES
                ):
                    raise SkillPackageError("invalid_skill_archive")
                _validate_external_type(info)
                parts = name.split("/")
                if info.is_dir():
                    valid = len(parts) == 2 and parts[1] == ""
                    if not valid or directory_info is not None:
                        raise SkillPackageError("invalid_skill_archive")
                    directory_info = info
                    candidate_id = parts[0]
                else:
                    valid = len(parts) == 2 and parts[1] == "SKILL.md"
                    if not valid or file_info is not None:
                        raise SkillPackageError("invalid_skill_archive")
                    file_info = info
                    candidate_id = parts[0]
                if skill_id is None:
                    skill_id = candidate_id
                elif candidate_id != skill_id:
                    raise SkillPackageError("invalid_skill_archive")
            if file_info is None or skill_id is None:
                raise SkillPackageError("invalid_skill_archive")
            if directory_info is not None and directory_info.filename != f"{skill_id}/":
                raise SkillPackageError("invalid_skill_archive")
            with package.open(file_info, "r") as handle:
                raw = handle.read(MAX_SKILL_FILE_BYTES + 1)
                if len(raw) > MAX_SKILL_FILE_BYTES or handle.read(1):
                    raise SkillPackageError("invalid_skill_archive")
    except SkillPackageError:
        raise
    except (OSError, EOFError, RuntimeError, zipfile.BadZipFile, zipfile.LargeZipFile):
        raise SkillPackageError("invalid_skill_archive") from None
    try:
        definition = _parse_skill_document(raw, SkillSource.WORKSPACE, skill_id)
    except (_EntryError, TypeError, ValueError):
        raise SkillPackageError("invalid_skill_archive") from None
    return _ParsedPackage(definition.descriptor, raw)


def _validate_real_directory(path: Path) -> None:
    metadata = os.lstat(path)
    if _is_reparse(metadata) or not stat.S_ISDIR(metadata.st_mode):
        raise SkillPackageError("skill_install_failed")


def _ensure_catalog_root(root: Path) -> None:
    missing: list[Path] = []
    current = root
    while True:
        try:
            _validate_real_directory(current)
            break
        except FileNotFoundError:
            missing.append(current)
            parent = current.parent
            if parent == current:
                raise SkillPackageError("skill_install_failed") from None
            current = parent
        except OSError:
            raise SkillPackageError("skill_install_failed") from None
    for directory in reversed(missing):
        try:
            _validate_real_directory(directory.parent)
            directory.mkdir(exist_ok=False)
            _validate_real_directory(directory)
        except (OSError, SkillPackageError):
            raise SkillPackageError("skill_install_failed") from None
    try:
        _validate_real_directory(root)
    except (OSError, SkillPackageError):
        raise SkillPackageError("skill_install_failed") from None


def _restore_cleanup_claim(claim: Path, staging: Path) -> None:
    try:
        os.lstat(staging)
        return
    except FileNotFoundError:
        pass
    except OSError:
        return
    try:
        os.rename(claim, staging)
    except OSError:
        return


def _remove_exact_staging(staging: Path) -> None:
    claim = staging.with_name(f"{staging.name}.cleanup")
    try:
        _validate_real_directory(staging.parent)
        os.lstat(claim)
        return
    except FileNotFoundError:
        pass
    except (OSError, SkillPackageError):
        return
    try:
        os.rename(staging, claim)
    except OSError:
        return
    cleaned = False
    try:
        metadata = os.lstat(claim)
        if _is_reparse(metadata) or not stat.S_ISDIR(metadata.st_mode):
            return
        definition = claim / "SKILL.md"
        try:
            definition_metadata = os.lstat(definition)
        except FileNotFoundError:
            pass
        except OSError:
            return
        else:
            if _is_reparse(definition_metadata) or not stat.S_ISREG(
                definition_metadata.st_mode
            ):
                return
            try:
                definition.unlink()
            except OSError:
                return
        try:
            claim.rmdir()
            cleaned = True
        except OSError:
            return
    finally:
        if not cleaned:
            _restore_cleanup_claim(claim, staging)


class SkillPackageInstaller:
    def __init__(
        self,
        workspace_skill_root: Path,
        *,
        id_factory: Callable[[], str] = _uuid4_hex,
    ) -> None:
        if not isinstance(workspace_skill_root, Path):
            raise TypeError("workspace_skill_root must be Path")
        if not callable(id_factory):
            raise TypeError("id_factory must be callable")
        self._workspace_skill_root = Path(os.path.abspath(workspace_skill_root))
        self._id_factory = id_factory

    @property
    def workspace_skill_root(self) -> Path:
        return self._workspace_skill_root

    def inspect(self, archive: bytes) -> SkillDescriptor:
        return _parse_package(archive).descriptor

    def install(self, archive: bytes) -> SkillDescriptor:
        parsed = _parse_package(archive)
        try:
            operation_id = self._id_factory()
        except Exception:
            raise SkillPackageError("skill_install_failed") from None
        if not isinstance(operation_id, str) or _OPERATION_ID.fullmatch(operation_id) is None:
            raise SkillPackageError("skill_install_failed")
        root = self._workspace_skill_root
        _ensure_catalog_root(root)
        destination = root / parsed.descriptor.skill_id
        try:
            destination_metadata = os.lstat(destination)
        except FileNotFoundError:
            pass
        except OSError:
            raise SkillPackageError("skill_install_failed") from None
        else:
            if _is_reparse(destination_metadata) or not stat.S_ISDIR(
                destination_metadata.st_mode
            ):
                raise SkillPackageError("skill_install_failed")
            raise SkillPackageError("skill_already_exists")

        staging = root / f".import-{operation_id}"
        try:
            staging_metadata = os.lstat(staging)
        except FileNotFoundError:
            pass
        except OSError:
            raise SkillPackageError("skill_install_failed") from None
        else:
            if _is_reparse(staging_metadata) or not stat.S_ISDIR(
                staging_metadata.st_mode
            ):
                raise SkillPackageError("skill_install_failed")
            raise SkillPackageError("skill_already_exists")
        published = False
        staging_created = False
        try:
            _validate_real_directory(root)
            staging.mkdir(exist_ok=False)
            staging_created = True
            _validate_real_directory(staging)
            with (staging / "SKILL.md").open("xb") as handle:
                handle.write(parsed.raw_definition)
            reread = _read_definition(
                staging / "SKILL.md",
                SkillSource.WORKSPACE,
                parsed.descriptor.skill_id,
            )
            if reread.descriptor != parsed.descriptor:
                raise SkillPackageError("skill_install_failed")
            _validate_real_directory(root)
            try:
                os.lstat(destination)
            except FileNotFoundError:
                pass
            else:
                raise SkillPackageError("skill_already_exists")
            staging.rename(destination)
            published = True
            return reread.descriptor
        except FileExistsError:
            raise SkillPackageError("skill_already_exists") from None
        except SkillPackageError:
            raise
        except (_EntryError, OSError):
            raise SkillPackageError("skill_install_failed") from None
        finally:
            if staging_created and not published:
                _remove_exact_staging(staging)

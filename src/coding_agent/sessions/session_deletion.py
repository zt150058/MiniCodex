from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
import json
import os
from pathlib import Path
import re
import stat
from typing import Mapping
from uuid import uuid4

from .session import SessionStoreError
from .session_store import SessionDeletionManifest, SessionStore


_INTERNAL_DIRECTORY = ".coding-agent"
_LOG_DIRECTORY = "logs"
_STAGING_DIRECTORY = "deletion-staging"
_MANIFEST_NAME = "manifest.json"
_MANIFEST_TEMP_NAME = "manifest.tmp"
_MANIFEST_SCHEMA_VERSION = 1
_MAX_MANIFEST_BYTES = 4_096
_ID_PATTERN = re.compile(r"[0-9a-f]{32}\Z")
_MANIFEST_FIELDS = frozenset(
    {
        "schema_version",
        "operation_id",
        "session_id",
        "audit_run_ids",
        "staged_audit_run_ids",
    }
)
_REPARSE_ATTRIBUTE = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)


def _uuid4_hex() -> str:
    return uuid4().hex


def _require_id(value: object, field_name: str) -> str:
    if type(value) is not str or _ID_PATTERN.fullmatch(value) is None:
        raise ValueError(f"{field_name} must be a lowercase UUID hex string")
    return value


def _require_id_tuple(value: object, field_name: str) -> tuple[str, ...]:
    if type(value) is not tuple:
        raise TypeError(f"{field_name} must be tuple")
    for item in value:
        _require_id(item, field_name)
    if len(set(value)) != len(value):
        raise ValueError(f"{field_name} must contain unique ids")
    return value


def _is_reparse(metadata: os.stat_result) -> bool:
    return stat.S_ISLNK(metadata.st_mode) or bool(
        getattr(metadata, "st_file_attributes", 0) & _REPARSE_ATTRIBUTE
    )


def _lstat(path: Path) -> os.stat_result | None:
    try:
        return os.lstat(path)
    except FileNotFoundError:
        return None


def _require_real_directory(path: Path) -> None:
    metadata = os.lstat(path)
    if _is_reparse(metadata) or not stat.S_ISDIR(metadata.st_mode):
        raise OSError("unsafe directory")


def _regular_file_exists(path: Path) -> bool:
    metadata = _lstat(path)
    if metadata is None:
        return False
    if _is_reparse(metadata) or not stat.S_ISREG(metadata.st_mode):
        raise OSError("unsafe file")
    return True


def _canonical_json(value: Mapping[str, object]) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


@dataclass(frozen=True, slots=True)
class SessionDeletionResult:
    session_id: str
    run_ids: tuple[str, ...] = field(repr=False)
    cleanup_pending: bool

    def __post_init__(self) -> None:
        _require_id(self.session_id, "session_id")
        _require_id_tuple(self.run_ids, "run_ids")
        if type(self.cleanup_pending) is not bool:
            raise TypeError("cleanup_pending must be bool")


class SessionDeletionError(RuntimeError):
    def __init__(self, code: str) -> None:
        if not isinstance(code, str) or not code:
            raise ValueError("invalid session deletion error code")
        self.code = code
        super().__init__(code)

    def __repr__(self) -> str:
        return f"SessionDeletionError({self.code!r})"


@dataclass(frozen=True, slots=True)
class _Operation:
    operation_id: str
    session_id: str
    run_ids: tuple[str, ...]
    audit_run_ids: tuple[str, ...]
    staged_audit_run_ids: tuple[str, ...]
    directory: Path = field(repr=False)

    @property
    def manifest_path(self) -> Path:
        return self.directory / _MANIFEST_NAME


@dataclass(frozen=True, slots=True)
class _RecoveryPlan:
    directory: Path = field(repr=False)
    operation: _Operation | None
    session_exists: bool | None


def _manifest_payload(operation: _Operation) -> dict[str, object]:
    return {
        "schema_version": _MANIFEST_SCHEMA_VERSION,
        "operation_id": operation.operation_id,
        "session_id": operation.session_id,
        "audit_run_ids": list(operation.audit_run_ids),
        "staged_audit_run_ids": list(operation.staged_audit_run_ids),
    }


class SessionDeletionService:
    def __init__(
        self,
        workspace: Path,
        store: SessionStore,
        *,
        operation_id_factory: Callable[[], str] = _uuid4_hex,
    ) -> None:
        if not isinstance(workspace, Path):
            raise TypeError("workspace must be Path")
        if not callable(operation_id_factory):
            raise TypeError("operation_id_factory must be callable")
        requested = Path(os.path.abspath(workspace))
        try:
            _require_real_directory(requested)
            normalized = requested.resolve(strict=True)
        except OSError:
            raise SessionDeletionError("session_delete_failed") from None
        store_workspace = getattr(store, "workspace", None)
        if not isinstance(store_workspace, Path) or Path(
            os.path.abspath(store_workspace)
        ) != normalized:
            raise SessionDeletionError("session_delete_failed")
        self._workspace = normalized
        self._store = store
        self._operation_id_factory = operation_id_factory

    @property
    def workspace(self) -> Path:
        return self._workspace

    @property
    def store(self) -> SessionStore:
        return self._store

    @property
    def _internal_root(self) -> Path:
        return self._workspace / _INTERNAL_DIRECTORY

    @property
    def _logs_root(self) -> Path:
        return self._internal_root / _LOG_DIRECTORY

    @property
    def _staging_root(self) -> Path:
        return self._internal_root / _STAGING_DIRECTORY

    def _audit_path(self, audit_run_id: str) -> Path:
        _require_id(audit_run_id, "audit_run_id")
        return self._logs_root / f"{audit_run_id}.jsonl"

    def _staged_path(self, operation: _Operation, audit_run_id: str) -> Path:
        _require_id(audit_run_id, "audit_run_id")
        return operation.directory / f"{audit_run_id}.jsonl"

    def _validate_internal(self) -> None:
        _require_real_directory(self._workspace)
        _require_real_directory(self._internal_root)

    def _logs_root_exists(self) -> bool:
        self._validate_internal()
        metadata = _lstat(self._logs_root)
        if metadata is None:
            return False
        if _is_reparse(metadata) or not stat.S_ISDIR(metadata.st_mode):
            raise OSError("unsafe logs directory")
        return True

    def _ensure_logs_root(self) -> None:
        if self._logs_root_exists():
            return
        _require_real_directory(self._internal_root)
        self._logs_root.mkdir(exist_ok=False)
        _require_real_directory(self._logs_root)

    def _ensure_staging_root(self) -> None:
        self._validate_internal()
        metadata = _lstat(self._staging_root)
        if metadata is None:
            self._staging_root.mkdir(exist_ok=False)
        _require_real_directory(self._staging_root)

    def _public_file_exists(self, audit_run_id: str) -> bool:
        if not self._logs_root_exists():
            return False
        return _regular_file_exists(self._audit_path(audit_run_id))

    @staticmethod
    def _translate_delete_error(error: Exception) -> SessionDeletionError:
        if isinstance(error, SessionDeletionError):
            return error
        if isinstance(error, SessionStoreError) and error.code in {
            "session_not_found",
            "invalid_session_state",
        }:
            return SessionDeletionError(error.code)
        return SessionDeletionError("session_delete_failed")

    def _remove_unpublished_operation(self, directory: Path) -> None:
        temp = directory / _MANIFEST_TEMP_NAME
        try:
            metadata = _lstat(directory)
            if (
                metadata is None
                or _is_reparse(metadata)
                or not stat.S_ISDIR(metadata.st_mode)
            ):
                return
            if _regular_file_exists(temp):
                temp.unlink()
            directory.rmdir()
        except OSError:
            return

    def _prepare_operation(self, manifest: SessionDeletionManifest) -> _Operation:
        if type(manifest) is not SessionDeletionManifest:
            raise SessionDeletionError("session_delete_failed")
        try:
            operation_id = self._operation_id_factory()
        except Exception:
            raise SessionDeletionError("session_delete_failed") from None
        try:
            _require_id(operation_id, "operation_id")
            self._ensure_staging_root()
            logs_exist = self._logs_root_exists()
            staged_ids = tuple(
                audit_id
                for audit_id in manifest.audit_run_ids
                if logs_exist and _regular_file_exists(self._audit_path(audit_id))
            )
            directory = self._staging_root / operation_id
            if _lstat(directory) is not None:
                raise OSError("operation collision")
            directory.mkdir(exist_ok=False)
            _require_real_directory(directory)
            operation = _Operation(
                operation_id=operation_id,
                session_id=manifest.session_id,
                run_ids=manifest.run_ids,
                audit_run_ids=manifest.audit_run_ids,
                staged_audit_run_ids=staged_ids,
                directory=directory,
            )
            raw = _canonical_json(_manifest_payload(operation))
            if len(raw) > _MAX_MANIFEST_BYTES:
                raise OSError("manifest too large")
            temp = directory / _MANIFEST_TEMP_NAME
            with temp.open("xb") as handle:
                handle.write(raw)
                handle.flush()
                os.fsync(handle.fileno())
            if not _regular_file_exists(temp) or _lstat(operation.manifest_path) is not None:
                raise OSError("unsafe manifest")
            temp.rename(operation.manifest_path)
            if not _regular_file_exists(operation.manifest_path):
                raise OSError("unsafe manifest")
            return operation
        except SessionDeletionError:
            raise
        except (OSError, TypeError, ValueError):
            directory_value = locals().get("directory")
            if isinstance(directory_value, Path):
                self._remove_unpublished_operation(directory_value)
            raise SessionDeletionError("session_delete_failed") from None

    def _operation_entry_names(self, operation: _Operation) -> tuple[str, ...]:
        _require_real_directory(operation.directory)
        try:
            return tuple(sorted(entry.name for entry in os.scandir(operation.directory)))
        except OSError:
            raise OSError("operation unavailable") from None

    def _validate_operation_members(self, operation: _Operation) -> None:
        allowed = {_MANIFEST_NAME}
        allowed.update(f"{audit_id}.jsonl" for audit_id in operation.staged_audit_run_ids)
        if set(self._operation_entry_names(operation)) - allowed:
            raise OSError("unexpected operation entry")
        if not _regular_file_exists(operation.manifest_path):
            raise OSError("manifest unavailable")

    def _stage_existing_logs(self, operation: _Operation) -> None:
        self._validate_operation_members(operation)
        staged_set = set(operation.staged_audit_run_ids)
        for audit_id in operation.audit_run_ids:
            public_exists = self._public_file_exists(audit_id)
            if audit_id not in staged_set:
                if public_exists:
                    raise OSError("unexpected audit source")
                continue
            if not public_exists:
                raise OSError("audit source disappeared")
            staged = self._staged_path(operation, audit_id)
            if _lstat(staged) is not None:
                raise OSError("staged collision")
            os.rename(self._audit_path(audit_id), staged)
            if self._public_file_exists(audit_id) or not _regular_file_exists(staged):
                raise OSError("audit staging failed")

    def _remove_restored_operation(self, operation: _Operation) -> None:
        self._validate_operation_members(operation)
        for audit_id in operation.staged_audit_run_ids:
            if _regular_file_exists(self._staged_path(operation, audit_id)):
                raise OSError("staged audit remains")
        operation.manifest_path.unlink()
        operation.directory.rmdir()

    def _restore_logs_without_overwrite(self, operation: _Operation) -> None:
        self._validate_operation_members(operation)
        for audit_id in operation.staged_audit_run_ids:
            staged = self._staged_path(operation, audit_id)
            staged_exists = _regular_file_exists(staged)
            public_exists = self._public_file_exists(audit_id)
            if staged_exists and public_exists:
                raise OSError("restore collision")
            if staged_exists:
                self._ensure_logs_root()
                os.rename(staged, self._audit_path(audit_id))
                if not self._public_file_exists(audit_id) or _lstat(staged) is not None:
                    raise OSError("restore failed")
            elif not public_exists:
                raise OSError("audit log unavailable")
        self._remove_restored_operation(operation)

    def _finish_cleanup(self, operation: _Operation) -> bool:
        try:
            self._validate_operation_members(operation)
            for audit_id in operation.staged_audit_run_ids:
                if self._public_file_exists(audit_id):
                    return False
                staged = self._staged_path(operation, audit_id)
                if _regular_file_exists(staged):
                    staged.unlink()
            self._validate_operation_members(operation)
            operation.manifest_path.unlink()
            operation.directory.rmdir()
            return True
        except OSError:
            return False

    def delete(self, session_id: str) -> SessionDeletionResult:
        try:
            _require_id(session_id, "session_id")
            manifest = self._store.get_session_deletion_manifest(session_id)
            operation = self._prepare_operation(manifest)
        except Exception as error:
            raise self._translate_delete_error(error) from None
        try:
            self._stage_existing_logs(operation)
            self._store.delete_session(manifest)
        except Exception as error:
            try:
                self._restore_logs_without_overwrite(operation)
            except Exception:
                raise SessionDeletionError(
                    "session_deletion_recovery_failed"
                ) from None
            raise self._translate_delete_error(error) from None
        cleanup_pending = not self._finish_cleanup(operation)
        return SessionDeletionResult(
            session_id=manifest.session_id,
            run_ids=manifest.run_ids,
            cleanup_pending=cleanup_pending,
        )

    def _decode_operation(self, directory: Path) -> _Operation:
        manifest_path = directory / _MANIFEST_NAME
        if not _regular_file_exists(manifest_path):
            raise OSError("manifest unavailable")
        with manifest_path.open("rb") as handle:
            raw = handle.read(_MAX_MANIFEST_BYTES + 1)
        if len(raw) > _MAX_MANIFEST_BYTES:
            raise OSError("manifest too large")
        try:
            decoded = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise OSError("invalid manifest") from None
        if not isinstance(decoded, dict) or set(decoded) != _MANIFEST_FIELDS:
            raise OSError("invalid manifest")
        if decoded.get("schema_version") != _MANIFEST_SCHEMA_VERSION or type(
            decoded.get("schema_version")
        ) is not int:
            raise OSError("invalid manifest")
        try:
            operation_id = _require_id(decoded["operation_id"], "operation_id")
            session_id = _require_id(decoded["session_id"], "session_id")
            audit_raw = decoded["audit_run_ids"]
            staged_raw = decoded["staged_audit_run_ids"]
            if type(audit_raw) is not list or type(staged_raw) is not list:
                raise TypeError
            audit_ids = _require_id_tuple(tuple(audit_raw), "audit_run_ids")
            staged_ids = _require_id_tuple(
                tuple(staged_raw),
                "staged_audit_run_ids",
            )
        except (KeyError, TypeError, ValueError):
            raise OSError("invalid manifest") from None
        if operation_id != directory.name:
            raise OSError("invalid manifest")
        expected_staged = tuple(item for item in audit_ids if item in set(staged_ids))
        if expected_staged != staged_ids:
            raise OSError("invalid manifest")
        operation = _Operation(
            operation_id=operation_id,
            session_id=session_id,
            run_ids=(),
            audit_run_ids=audit_ids,
            staged_audit_run_ids=staged_ids,
            directory=directory,
        )
        if _canonical_json(_manifest_payload(operation)) != raw:
            raise OSError("invalid manifest")
        self._validate_operation_members(operation)
        return operation

    def _recover_existing_session(self, operation: _Operation) -> None:
        self._restore_logs_without_overwrite(operation)

    def _recover_deleted_session(self, operation: _Operation) -> None:
        self._validate_operation_members(operation)
        for audit_id in operation.staged_audit_run_ids:
            staged = self._staged_path(operation, audit_id)
            staged_exists = _regular_file_exists(staged)
            public_exists = self._public_file_exists(audit_id)
            if public_exists:
                raise OSError("post-commit public conflict")
            if staged_exists:
                staged.unlink()
        self._validate_operation_members(operation)
        operation.manifest_path.unlink()
        operation.directory.rmdir()

    def _preflight_recovery_operation(self, directory: Path) -> _RecoveryPlan:
        _require_real_directory(directory)
        names = tuple(sorted(entry.name for entry in os.scandir(directory)))
        if _MANIFEST_NAME not in names:
            if names:
                raise OSError("manifest unavailable")
            return _RecoveryPlan(
                directory=directory,
                operation=None,
                session_exists=None,
            )
        operation = self._decode_operation(directory)
        session_exists = self._store.session_exists(operation.session_id)
        for audit_id in operation.staged_audit_run_ids:
            staged_exists = _regular_file_exists(
                self._staged_path(operation, audit_id)
            )
            public_exists = self._public_file_exists(audit_id)
            if session_exists:
                if staged_exists == public_exists:
                    raise OSError("invalid pre-commit audit state")
            elif public_exists:
                raise OSError("post-commit public conflict")
        return _RecoveryPlan(
            directory=directory,
            operation=operation,
            session_exists=session_exists,
        )

    def _execute_recovery_plan(self, plan: _RecoveryPlan) -> None:
        if plan.operation is None:
            plan.directory.rmdir()
            return
        if plan.session_exists:
            self._recover_existing_session(plan.operation)
        else:
            self._recover_deleted_session(plan.operation)

    def recover_pending(self) -> None:
        try:
            self._validate_internal()
            metadata = _lstat(self._staging_root)
            if metadata is None:
                return
            if _is_reparse(metadata) or not stat.S_ISDIR(metadata.st_mode):
                raise OSError("unsafe staging root")
            entries = tuple(sorted(entry.name for entry in os.scandir(self._staging_root)))
            for name in entries:
                _require_id(name, "operation_id")
                directory = self._staging_root / name
                _require_real_directory(directory)
            plans = tuple(
                self._preflight_recovery_operation(self._staging_root / name)
                for name in entries
            )
            public_targets: set[Path] = set()
            for plan in plans:
                if plan.operation is None:
                    continue
                for audit_id in plan.operation.staged_audit_run_ids:
                    target = self._audit_path(audit_id)
                    if target in public_targets:
                        raise OSError("duplicate recovery target")
                    public_targets.add(target)
            for plan in plans:
                self._execute_recovery_plan(plan)
        except Exception:
            raise SessionDeletionError("session_deletion_recovery_failed") from None

from __future__ import annotations

import os
from pathlib import Path
import json

import pytest

from coding_agent.session import (
    SessionRunResult,
    SessionRunStatus,
    SessionStoreError,
    make_safe_run_summary,
)
from coding_agent.session_deletion import (
    SessionDeletionError,
    SessionDeletionResult,
    SessionDeletionService,
)
from coding_agent.session_store import SQLiteSessionStore, SessionDeletionManifest


SESSION_ID = "1" * 32
RUN_ID = "2" * 32
AUDIT_ID = "a" * 32
MODEL_ID = "selected-model"


def _failed_result(run_id: str, audit_run_id: str) -> SessionRunResult:
    return SessionRunResult(
        run_id=run_id,
        status=SessionRunStatus.FAILED,
        agent_status="failed",
        termination_reason="empty_model_response",
        audit_run_id=audit_run_id,
        safe_summary=make_safe_run_summary(
            None,
            status="failed",
            termination_reason="empty_model_response",
        ),
        final_report=None,
    )


def _store_with_terminal_session(
    workspace: Path,
    *,
    audit_ids: tuple[str, ...] = (AUDIT_ID,),
) -> tuple[SQLiteSessionStore, str, tuple[str, ...]]:
    generated = iter(f"{digit:x}" * 32 for digit in range(1, 16))
    store = SQLiteSessionStore(workspace, id_factory=lambda: next(generated))
    store.initialize()
    submission = store.create_session("target", model_id=MODEL_ID)
    run_ids = [submission.run.run_id]
    store.finish_run(_failed_result(submission.run.run_id, audit_ids[0]))
    for position, audit_id in enumerate(audit_ids[1:], start=2):
        submission = store.submit_message(
            submission.session.session_id,
            f"target {position}",
            model_id=MODEL_ID,
        )
        run_ids.append(submission.run.run_id)
        store.finish_run(_failed_result(submission.run.run_id, audit_id))
    return store, submission.session.session_id, tuple(run_ids)


def _write_audit(workspace: Path, audit_id: str, content: str = "audit") -> Path:
    logs = workspace / ".coding-agent" / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    path = logs / f"{audit_id}.jsonl"
    path.write_text(content, encoding="utf-8")
    return path


def _operation_entries(workspace: Path) -> tuple[str, ...]:
    root = workspace / ".coding-agent" / "deletion-staging"
    if not root.exists():
        return ()
    return tuple(sorted(item.name for item in root.iterdir()))


def _write_operation(
    workspace: Path,
    *,
    operation_id: str,
    session_id: str,
    audit_ids: tuple[str, ...],
    staged_ids: tuple[str, ...],
) -> Path:
    operation = (
        workspace
        / ".coding-agent"
        / "deletion-staging"
        / operation_id
    )
    operation.mkdir(parents=True)
    payload = {
        "schema_version": 1,
        "operation_id": operation_id,
        "session_id": session_id,
        "audit_run_ids": list(audit_ids),
        "staged_audit_run_ids": list(staged_ids),
    }
    (operation / "manifest.json").write_text(
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ),
        encoding="utf-8",
    )
    return operation


def test_deletion_public_types_are_immutable_private_and_stable(
    tmp_path: Path,
) -> None:
    store, _session_id, _run_ids = _store_with_terminal_session(tmp_path)
    service = SessionDeletionService(
        tmp_path,
        store,
        operation_id_factory=lambda: "f" * 32,
    )
    result = SessionDeletionResult(SESSION_ID, (RUN_ID,), False)
    error = SessionDeletionError("session_delete_failed")

    assert result.session_id == SESSION_ID
    assert result.run_ids == (RUN_ID,)
    assert result.cleanup_pending is False
    assert RUN_ID not in repr(result)
    assert str(error) == "session_delete_failed"
    assert repr(error) == "SessionDeletionError('session_delete_failed')"
    assert service.workspace == tmp_path.resolve(strict=True)
    assert service.store is store
    assert service._audit_path(AUDIT_ID) == (
        tmp_path.resolve(strict=True)
        / ".coding-agent"
        / "logs"
        / f"{AUDIT_ID}.jsonl"
    )
    with pytest.raises(Exception):
        result.cleanup_pending = True  # type: ignore[misc]


@pytest.mark.parametrize(
    ("session_id", "run_ids", "cleanup_pending", "error"),
    (
        ("invalid", (RUN_ID,), False, ValueError),
        (SESSION_ID, [RUN_ID], False, TypeError),
        (SESSION_ID, ("invalid",), False, ValueError),
        (SESSION_ID, (RUN_ID, RUN_ID), False, ValueError),
        (SESSION_ID, (RUN_ID,), 1, TypeError),
    ),
)
def test_deletion_result_rejects_invalid_public_values(
    session_id: object,
    run_ids: object,
    cleanup_pending: object,
    error: type[Exception],
) -> None:
    with pytest.raises(error):
        SessionDeletionResult(  # type: ignore[arg-type]
            session_id,
            run_ids,
            cleanup_pending,
        )


def test_delete_removes_only_manifest_logs_and_relational_session(
    tmp_path: Path,
) -> None:
    audit_ids = ("a" * 32, "b" * 32)
    store, session_id, run_ids = _store_with_terminal_session(
        tmp_path,
        audit_ids=audit_ids,
    )
    targets = tuple(_write_audit(tmp_path, audit_id) for audit_id in audit_ids)
    unrelated = _write_audit(tmp_path, "c" * 32, "unrelated")
    service = SessionDeletionService(
        tmp_path,
        store,
        operation_id_factory=lambda: "f" * 32,
    )

    result = service.delete(session_id)

    assert result == SessionDeletionResult(session_id, run_ids, False)
    assert store.session_exists(session_id) is False
    assert all(not target.exists() for target in targets)
    assert unrelated.read_text(encoding="utf-8") == "unrelated"
    assert _operation_entries(tmp_path) == ()


def test_delete_accepts_missing_expected_log(tmp_path: Path) -> None:
    store, session_id, run_ids = _store_with_terminal_session(tmp_path)
    unrelated = _write_audit(tmp_path, "c" * 32, "unrelated")

    result = SessionDeletionService(
        tmp_path,
        store,
        operation_id_factory=lambda: "f" * 32,
    ).delete(session_id)

    assert result == SessionDeletionResult(session_id, run_ids, False)
    assert store.session_exists(session_id) is False
    assert unrelated.read_text(encoding="utf-8") == "unrelated"
    assert _operation_entries(tmp_path) == ()


def test_failure_before_manifest_publication_preserves_session_and_log(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store, session_id, _run_ids = _store_with_terminal_session(tmp_path)
    target = _write_audit(tmp_path, AUDIT_ID, "private audit")
    real_rename = Path.rename

    def fail_manifest_rename(source: Path, target_path: Path) -> Path:
        if source.name == "manifest.tmp":
            raise PermissionError("private path detail")
        return real_rename(source, target_path)

    monkeypatch.setattr(Path, "rename", fail_manifest_rename)
    with pytest.raises(SessionDeletionError) as captured:
        SessionDeletionService(
            tmp_path,
            store,
            operation_id_factory=lambda: "f" * 32,
        ).delete(session_id)

    assert captured.value.code == "session_delete_failed"
    assert str(tmp_path) not in repr(captured.value)
    assert store.session_exists(session_id) is True
    assert target.read_text(encoding="utf-8") == "private audit"
    assert _operation_entries(tmp_path) == ()


def test_unpublished_cleanup_does_not_follow_swapped_operation_directory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store, session_id, _run_ids = _store_with_terminal_session(tmp_path)
    target = _write_audit(tmp_path, AUDIT_ID, "public audit")
    operation_id = "f" * 32
    operation = (
        tmp_path / ".coding-agent" / "deletion-staging" / operation_id
    )
    displaced = operation.with_name("owned-displaced")
    private = tmp_path / "private-operation-target"
    private.mkdir()
    private_temp = private / "manifest.tmp"
    private_temp.write_text("preserve", encoding="utf-8")
    real_rename = Path.rename

    def swap_parent_then_fail(source: Path, target_path: Path) -> Path:
        if source.name == "manifest.tmp":
            os.rename(operation, displaced)
            try:
                operation.symlink_to(private, target_is_directory=True)
            except OSError as exc:
                os.rename(displaced, operation)
                pytest.fail(f"target Windows environment must allow this test: {exc}")
            raise PermissionError("private path detail")
        return real_rename(source, target_path)

    monkeypatch.setattr(Path, "rename", swap_parent_then_fail)
    with pytest.raises(SessionDeletionError) as captured:
        SessionDeletionService(
            tmp_path,
            store,
            operation_id_factory=lambda: operation_id,
        ).delete(session_id)

    assert captured.value.code == "session_delete_failed"
    assert private_temp.read_text(encoding="utf-8") == "preserve"
    assert target.read_text(encoding="utf-8") == "public audit"
    assert store.session_exists(session_id) is True


def test_failure_after_one_log_move_restores_all_public_logs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    audit_ids = ("a" * 32, "b" * 32)
    store, session_id, _run_ids = _store_with_terminal_session(
        tmp_path,
        audit_ids=audit_ids,
    )
    targets = tuple(
        _write_audit(tmp_path, audit_id, f"audit-{index}")
        for index, audit_id in enumerate(audit_ids)
    )
    real_rename = os.rename
    audit_moves = 0

    def fail_second_audit_move(source: object, destination: object) -> None:
        nonlocal audit_moves
        source_path = Path(source)
        if source_path.parent.name == "logs" and source_path.suffix == ".jsonl":
            audit_moves += 1
            if audit_moves == 2:
                raise PermissionError("private path detail")
        real_rename(source, destination)

    monkeypatch.setattr(os, "rename", fail_second_audit_move)
    with pytest.raises(SessionDeletionError) as captured:
        SessionDeletionService(
            tmp_path,
            store,
            operation_id_factory=lambda: "f" * 32,
        ).delete(session_id)

    assert captured.value.code == "session_delete_failed"
    assert store.session_exists(session_id) is True
    assert [path.read_text(encoding="utf-8") for path in targets] == [
        "audit-0",
        "audit-1",
    ]
    assert _operation_entries(tmp_path) == ()


def test_database_delete_failure_rolls_back_staged_logs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store, session_id, _run_ids = _store_with_terminal_session(tmp_path)
    target = _write_audit(tmp_path, AUDIT_ID, "private audit")

    def fail_delete(manifest: SessionDeletionManifest) -> None:
        raise SessionStoreError("storage_unavailable")

    monkeypatch.setattr(store, "delete_session", fail_delete)
    with pytest.raises(SessionDeletionError) as captured:
        SessionDeletionService(
            tmp_path,
            store,
            operation_id_factory=lambda: "f" * 32,
        ).delete(session_id)

    assert captured.value.code == "session_delete_failed"
    assert store.session_exists(session_id) is True
    assert target.read_text(encoding="utf-8") == "private audit"
    assert _operation_entries(tmp_path) == ()


def test_restore_collision_fails_closed_and_preserves_recovery_state(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store, session_id, _run_ids = _store_with_terminal_session(tmp_path)
    target = _write_audit(tmp_path, AUDIT_ID, "original audit")

    def collide_then_fail(manifest: SessionDeletionManifest) -> None:
        target.write_text("collision", encoding="utf-8")
        raise SessionStoreError("storage_unavailable")

    monkeypatch.setattr(store, "delete_session", collide_then_fail)
    with pytest.raises(SessionDeletionError) as captured:
        SessionDeletionService(
            tmp_path,
            store,
            operation_id_factory=lambda: "f" * 32,
        ).delete(session_id)

    assert captured.value.code == "session_deletion_recovery_failed"
    assert store.session_exists(session_id) is True
    assert target.read_text(encoding="utf-8") == "collision"
    operation = (
        tmp_path / ".coding-agent" / "deletion-staging" / ("f" * 32)
    )
    assert (operation / f"{AUDIT_ID}.jsonl").read_text(encoding="utf-8") == (
        "original audit"
    )
    assert (operation / "manifest.json").is_file()


def test_post_commit_staged_delete_failure_returns_cleanup_pending(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store, session_id, run_ids = _store_with_terminal_session(tmp_path)
    target = _write_audit(tmp_path, AUDIT_ID, "private audit")
    operation_id = "f" * 32
    staged = (
        tmp_path
        / ".coding-agent"
        / "deletion-staging"
        / operation_id
        / f"{AUDIT_ID}.jsonl"
    )
    real_unlink = Path.unlink

    def fail_staged_unlink(path: Path, *args: object, **kwargs: object) -> None:
        if path == staged:
            raise PermissionError("private path detail")
        real_unlink(path, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", fail_staged_unlink)
    result = SessionDeletionService(
        tmp_path,
        store,
        operation_id_factory=lambda: operation_id,
    ).delete(session_id)

    assert result == SessionDeletionResult(session_id, run_ids, True)
    assert store.session_exists(session_id) is False
    assert not target.exists()
    assert staged.read_text(encoding="utf-8") == "private audit"
    assert (staged.parent / "manifest.json").is_file()


def test_recovery_existing_session_accepts_move_not_started(tmp_path: Path) -> None:
    store, session_id, _run_ids = _store_with_terminal_session(tmp_path)
    public = _write_audit(tmp_path, AUDIT_ID, "public audit")
    operation = _write_operation(
        tmp_path,
        operation_id="f" * 32,
        session_id=session_id,
        audit_ids=(AUDIT_ID,),
        staged_ids=(AUDIT_ID,),
    )

    SessionDeletionService(tmp_path, store).recover_pending()

    assert public.read_text(encoding="utf-8") == "public audit"
    assert not operation.exists()
    assert store.session_exists(session_id) is True


def test_recovery_existing_session_restores_partial_moves(tmp_path: Path) -> None:
    audit_ids = ("a" * 32, "b" * 32)
    store, session_id, _run_ids = _store_with_terminal_session(
        tmp_path,
        audit_ids=audit_ids,
    )
    first_public = _write_audit(tmp_path, audit_ids[0], "first")
    second_public = _write_audit(tmp_path, audit_ids[1], "second")
    operation = _write_operation(
        tmp_path,
        operation_id="f" * 32,
        session_id=session_id,
        audit_ids=audit_ids,
        staged_ids=audit_ids,
    )
    os.rename(first_public, operation / f"{audit_ids[0]}.jsonl")

    SessionDeletionService(tmp_path, store).recover_pending()

    assert first_public.read_text(encoding="utf-8") == "first"
    assert second_public.read_text(encoding="utf-8") == "second"
    assert not operation.exists()
    assert store.session_exists(session_id) is True


def test_recovery_deleted_session_finishes_staged_and_already_cleaned_ids(
    tmp_path: Path,
) -> None:
    audit_ids = ("a" * 32, "b" * 32)
    store, session_id, _run_ids = _store_with_terminal_session(
        tmp_path,
        audit_ids=audit_ids,
    )
    manifest = store.get_session_deletion_manifest(session_id)
    store.delete_session(manifest)
    operation = _write_operation(
        tmp_path,
        operation_id="f" * 32,
        session_id=session_id,
        audit_ids=audit_ids,
        staged_ids=audit_ids,
    )
    staged = operation / f"{audit_ids[0]}.jsonl"
    staged.write_text("staged first", encoding="utf-8")
    already_cleaned = _write_audit(tmp_path, audit_ids[1])
    already_cleaned.unlink()

    SessionDeletionService(tmp_path, store).recover_pending()

    assert store.session_exists(session_id) is False
    assert not staged.exists()
    assert not operation.exists()


def test_recovery_deleted_session_rejects_public_present_staged_missing(
    tmp_path: Path,
) -> None:
    store, session_id, _run_ids = _store_with_terminal_session(tmp_path)
    manifest = store.get_session_deletion_manifest(session_id)
    store.delete_session(manifest)
    public = _write_audit(tmp_path, AUDIT_ID, "public conflict")
    operation = _write_operation(
        tmp_path,
        operation_id="f" * 32,
        session_id=session_id,
        audit_ids=(AUDIT_ID,),
        staged_ids=(AUDIT_ID,),
    )

    with pytest.raises(SessionDeletionError) as captured:
        SessionDeletionService(tmp_path, store).recover_pending()

    assert captured.value.code == "session_deletion_recovery_failed"
    assert public.read_text(encoding="utf-8") == "public conflict"
    assert (operation / "manifest.json").is_file()


def test_recovery_deleted_session_rejects_public_and_staged_collision(
    tmp_path: Path,
) -> None:
    store, session_id, _run_ids = _store_with_terminal_session(tmp_path)
    manifest = store.get_session_deletion_manifest(session_id)
    store.delete_session(manifest)
    public = _write_audit(tmp_path, AUDIT_ID, "public conflict")
    operation = _write_operation(
        tmp_path,
        operation_id="f" * 32,
        session_id=session_id,
        audit_ids=(AUDIT_ID,),
        staged_ids=(AUDIT_ID,),
    )
    staged = operation / f"{AUDIT_ID}.jsonl"
    staged.write_text("staged conflict", encoding="utf-8")

    with pytest.raises(SessionDeletionError) as captured:
        SessionDeletionService(tmp_path, store).recover_pending()

    assert captured.value.code == "session_deletion_recovery_failed"
    assert public.read_text(encoding="utf-8") == "public conflict"
    assert staged.read_text(encoding="utf-8") == "staged conflict"
    assert (operation / "manifest.json").is_file()


def test_recovery_removes_only_empty_valid_operation_without_manifest(
    tmp_path: Path,
) -> None:
    store, _session_id, _run_ids = _store_with_terminal_session(tmp_path)
    operation = (
        tmp_path
        / ".coding-agent"
        / "deletion-staging"
        / ("f" * 32)
    )
    operation.mkdir(parents=True)

    SessionDeletionService(tmp_path, store).recover_pending()

    assert not operation.exists()


def _manifest_bytes(
    operation_id: str,
    session_id: str,
    *,
    audit_ids: tuple[str, ...] = (AUDIT_ID,),
    staged_ids: tuple[str, ...] = (AUDIT_ID,),
) -> bytes:
    return json.dumps(
        {
            "schema_version": 1,
            "operation_id": operation_id,
            "session_id": session_id,
            "audit_run_ids": list(audit_ids),
            "staged_audit_run_ids": list(staged_ids),
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


@pytest.mark.parametrize(
    "case",
    (
        "extra-field",
        "missing-field",
        "wrong-schema-type",
        "invalid-operation",
        "operation-mismatch",
        "duplicate-audit",
        "duplicate-staged",
        "staged-not-subset",
        "staged-order",
        "noncanonical",
        "non-utf8",
        "oversize",
    ),
)
def test_recovery_rejects_malformed_manifest_without_modifying_it(
    tmp_path: Path,
    case: str,
) -> None:
    store, session_id, _run_ids = _store_with_terminal_session(tmp_path)
    operation_id = "f" * 32
    operation = (
        tmp_path / ".coding-agent" / "deletion-staging" / operation_id
    )
    operation.mkdir(parents=True)
    payload: dict[str, object] = {
        "schema_version": 1,
        "operation_id": operation_id,
        "session_id": session_id,
        "audit_run_ids": ["a" * 32, "b" * 32],
        "staged_audit_run_ids": ["a" * 32, "b" * 32],
    }
    if case == "extra-field":
        payload["path"] = str(tmp_path)
    elif case == "missing-field":
        payload.pop("session_id")
    elif case == "wrong-schema-type":
        payload["schema_version"] = True
    elif case == "invalid-operation":
        payload["operation_id"] = "../unsafe"
    elif case == "operation-mismatch":
        payload["operation_id"] = "e" * 32
    elif case == "duplicate-audit":
        payload["audit_run_ids"] = ["a" * 32, "a" * 32]
    elif case == "duplicate-staged":
        payload["staged_audit_run_ids"] = ["a" * 32, "a" * 32]
    elif case == "staged-not-subset":
        payload["staged_audit_run_ids"] = ["c" * 32]
    elif case == "staged-order":
        payload["staged_audit_run_ids"] = ["b" * 32, "a" * 32]
    if case == "non-utf8":
        raw = b"\xff\xfe"
    elif case == "oversize":
        raw = b"x" * 4_097
    elif case == "noncanonical":
        raw = json.dumps(payload).encode("utf-8")
    else:
        raw = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    manifest = operation / "manifest.json"
    manifest.write_bytes(raw)

    with pytest.raises(SessionDeletionError) as captured:
        SessionDeletionService(tmp_path, store).recover_pending()

    assert captured.value.code == "session_deletion_recovery_failed"
    assert manifest.read_bytes() == raw
    assert store.session_exists(session_id) is True


def test_recovery_rejects_invalid_operation_name_and_nonempty_unpublished_dir(
    tmp_path: Path,
) -> None:
    store, session_id, _run_ids = _store_with_terminal_session(tmp_path)
    staging = tmp_path / ".coding-agent" / "deletion-staging"
    invalid = staging / "not-an-operation"
    invalid.mkdir(parents=True)
    marker = invalid / "private"
    marker.write_text("preserve", encoding="utf-8")

    with pytest.raises(SessionDeletionError) as captured:
        SessionDeletionService(tmp_path, store).recover_pending()

    assert captured.value.code == "session_deletion_recovery_failed"
    assert marker.read_text(encoding="utf-8") == "preserve"
    assert store.session_exists(session_id) is True

    invalid.rename(staging / ("f" * 32))
    with pytest.raises(SessionDeletionError):
        SessionDeletionService(tmp_path, store).recover_pending()
    assert (staging / ("f" * 32) / "private").is_file()


def test_delete_rejects_reparse_logs_root_without_reading_target(
    tmp_path: Path,
) -> None:
    store, session_id, _run_ids = _store_with_terminal_session(tmp_path)
    target_root = tmp_path / "private-logs"
    private = _write_audit(target_root.parent, AUDIT_ID, "private target")
    generated_logs = target_root.parent / ".coding-agent" / "logs"
    target_root.mkdir()
    private.rename(target_root / private.name)
    generated_logs.rmdir()
    logs = tmp_path / ".coding-agent" / "logs"
    try:
        logs.symlink_to(target_root, target_is_directory=True)
    except OSError as exc:
        pytest.fail(f"target Windows environment must allow this test: {exc}")

    with pytest.raises(SessionDeletionError) as captured:
        SessionDeletionService(tmp_path, store).delete(session_id)

    assert captured.value.code == "session_delete_failed"
    assert (target_root / f"{AUDIT_ID}.jsonl").read_text(encoding="utf-8") == (
        "private target"
    )
    assert store.session_exists(session_id) is True


def test_delete_rejects_reparse_staging_root_without_touching_target(
    tmp_path: Path,
) -> None:
    store, session_id, _run_ids = _store_with_terminal_session(tmp_path)
    target = tmp_path / "private-staging"
    target.mkdir()
    marker = target / "private"
    marker.write_text("preserve", encoding="utf-8")
    staging = tmp_path / ".coding-agent" / "deletion-staging"
    try:
        staging.symlink_to(target, target_is_directory=True)
    except OSError as exc:
        pytest.fail(f"target Windows environment must allow this test: {exc}")

    with pytest.raises(SessionDeletionError) as captured:
        SessionDeletionService(tmp_path, store).delete(session_id)

    assert captured.value.code == "session_delete_failed"
    assert marker.read_text(encoding="utf-8") == "preserve"
    assert store.session_exists(session_id) is True


def test_delete_rejects_reparse_audit_file_without_reading_target(
    tmp_path: Path,
) -> None:
    store, session_id, _run_ids = _store_with_terminal_session(tmp_path)
    logs = tmp_path / ".coding-agent" / "logs"
    logs.mkdir()
    private = tmp_path / "private-audit"
    private.write_text("preserve", encoding="utf-8")
    linked = logs / f"{AUDIT_ID}.jsonl"
    try:
        linked.symlink_to(private)
    except OSError as exc:
        pytest.fail(f"target Windows environment must allow this test: {exc}")

    with pytest.raises(SessionDeletionError) as captured:
        SessionDeletionService(tmp_path, store).delete(session_id)

    assert captured.value.code == "session_delete_failed"
    assert private.read_text(encoding="utf-8") == "preserve"
    assert store.session_exists(session_id) is True


def test_recovery_rejects_reparse_operation_manifest_and_staged_file(
    tmp_path: Path,
) -> None:
    store, session_id, _run_ids = _store_with_terminal_session(tmp_path)
    staging = tmp_path / ".coding-agent" / "deletion-staging"
    target_directory = tmp_path / "private-operation"
    target_directory.mkdir()
    marker = target_directory / "private"
    marker.write_text("preserve", encoding="utf-8")
    linked_operation = staging / ("d" * 32)
    staging.mkdir()
    try:
        linked_operation.symlink_to(target_directory, target_is_directory=True)
    except OSError as exc:
        pytest.fail(f"target Windows environment must allow this test: {exc}")
    with pytest.raises(SessionDeletionError):
        SessionDeletionService(tmp_path, store).recover_pending()
    assert marker.read_text(encoding="utf-8") == "preserve"
    linked_operation.unlink()

    operation = staging / ("e" * 32)
    operation.mkdir()
    private_manifest = tmp_path / "private-manifest"
    private_manifest.write_bytes(_manifest_bytes("e" * 32, session_id))
    try:
        (operation / "manifest.json").symlink_to(private_manifest)
    except OSError as exc:
        pytest.fail(f"target Windows environment must allow this test: {exc}")
    with pytest.raises(SessionDeletionError):
        SessionDeletionService(tmp_path, store).recover_pending()
    assert private_manifest.read_bytes() == _manifest_bytes("e" * 32, session_id)
    (operation / "manifest.json").unlink()

    (operation / "manifest.json").write_bytes(
        _manifest_bytes("e" * 32, session_id)
    )
    private_staged = tmp_path / "private-staged"
    private_staged.write_text("preserve", encoding="utf-8")
    try:
        (operation / f"{AUDIT_ID}.jsonl").symlink_to(private_staged)
    except OSError as exc:
        pytest.fail(f"target Windows environment must allow this test: {exc}")
    with pytest.raises(SessionDeletionError):
        SessionDeletionService(tmp_path, store).recover_pending()
    assert private_staged.read_text(encoding="utf-8") == "preserve"


def test_recovery_validates_all_operation_entries_before_removing_any(
    tmp_path: Path,
) -> None:
    store, _session_id, _run_ids = _store_with_terminal_session(tmp_path)
    staging = tmp_path / ".coding-agent" / "deletion-staging"
    valid_empty = staging / ("a" * 32)
    invalid = staging / "z-invalid"
    valid_empty.mkdir(parents=True)
    invalid.mkdir()

    with pytest.raises(SessionDeletionError) as captured:
        SessionDeletionService(tmp_path, store).recover_pending()

    assert captured.value.code == "session_deletion_recovery_failed"
    assert valid_empty.is_dir()
    assert invalid.is_dir()


def test_recovery_preflights_later_manifest_before_removing_first_operation(
    tmp_path: Path,
) -> None:
    store, _session_id, _run_ids = _store_with_terminal_session(tmp_path)
    staging = tmp_path / ".coding-agent" / "deletion-staging"
    first_empty = staging / ("a" * 32)
    later_malformed = staging / ("b" * 32)
    first_empty.mkdir(parents=True)
    later_malformed.mkdir()
    malformed = later_malformed / "manifest.json"
    malformed.write_bytes(b"not-json")

    with pytest.raises(SessionDeletionError) as captured:
        SessionDeletionService(tmp_path, store).recover_pending()

    assert captured.value.code == "session_deletion_recovery_failed"
    assert first_empty.is_dir()
    assert malformed.read_bytes() == b"not-json"


def test_deleted_recovery_preflights_later_conflict_before_unlinking_first(
    tmp_path: Path,
) -> None:
    audit_ids = ("a" * 32, "b" * 32)
    store, session_id, _run_ids = _store_with_terminal_session(
        tmp_path,
        audit_ids=audit_ids,
    )
    store.delete_session(store.get_session_deletion_manifest(session_id))
    operation = _write_operation(
        tmp_path,
        operation_id="f" * 32,
        session_id=session_id,
        audit_ids=audit_ids,
        staged_ids=audit_ids,
    )
    first_staged = operation / f"{audit_ids[0]}.jsonl"
    first_staged.write_text("preserve staged", encoding="utf-8")
    later_public = _write_audit(tmp_path, audit_ids[1], "public conflict")

    with pytest.raises(SessionDeletionError) as captured:
        SessionDeletionService(tmp_path, store).recover_pending()

    assert captured.value.code == "session_deletion_recovery_failed"
    assert first_staged.read_text(encoding="utf-8") == "preserve staged"
    assert later_public.read_text(encoding="utf-8") == "public conflict"
    assert (operation / "manifest.json").is_file()


def test_existing_recovery_preflights_later_conflict_before_restoring_first(
    tmp_path: Path,
) -> None:
    audit_ids = ("a" * 32, "b" * 32)
    store, session_id, _run_ids = _store_with_terminal_session(
        tmp_path,
        audit_ids=audit_ids,
    )
    operation = _write_operation(
        tmp_path,
        operation_id="f" * 32,
        session_id=session_id,
        audit_ids=audit_ids,
        staged_ids=audit_ids,
    )
    first_staged = operation / f"{audit_ids[0]}.jsonl"
    first_staged.write_text("preserve staged", encoding="utf-8")
    later_staged = operation / f"{audit_ids[1]}.jsonl"
    later_staged.write_text("staged conflict", encoding="utf-8")
    later_public = _write_audit(tmp_path, audit_ids[1], "public conflict")
    first_public = (
        tmp_path / ".coding-agent" / "logs" / f"{audit_ids[0]}.jsonl"
    )

    with pytest.raises(SessionDeletionError) as captured:
        SessionDeletionService(tmp_path, store).recover_pending()

    assert captured.value.code == "session_deletion_recovery_failed"
    assert first_staged.read_text(encoding="utf-8") == "preserve staged"
    assert not first_public.exists()
    assert later_staged.read_text(encoding="utf-8") == "staged conflict"
    assert later_public.read_text(encoding="utf-8") == "public conflict"


def test_recovery_preflights_duplicate_public_targets_across_operations(
    tmp_path: Path,
) -> None:
    store, first_session_id, _run_ids = _store_with_terminal_session(tmp_path)
    second_submission = store.create_session(
        "second target", model_id=MODEL_ID
    )
    store.finish_run(_failed_result(second_submission.run.run_id, AUDIT_ID))
    first_operation = _write_operation(
        tmp_path,
        operation_id="e" * 32,
        session_id=first_session_id,
        audit_ids=(AUDIT_ID,),
        staged_ids=(AUDIT_ID,),
    )
    second_operation = _write_operation(
        tmp_path,
        operation_id="f" * 32,
        session_id=second_submission.session.session_id,
        audit_ids=(AUDIT_ID,),
        staged_ids=(AUDIT_ID,),
    )
    first_staged = first_operation / f"{AUDIT_ID}.jsonl"
    second_staged = second_operation / f"{AUDIT_ID}.jsonl"
    first_staged.write_text("first staged", encoding="utf-8")
    second_staged.write_text("second staged", encoding="utf-8")
    public = tmp_path / ".coding-agent" / "logs" / f"{AUDIT_ID}.jsonl"

    with pytest.raises(SessionDeletionError) as captured:
        SessionDeletionService(tmp_path, store).recover_pending()

    assert captured.value.code == "session_deletion_recovery_failed"
    assert first_staged.read_text(encoding="utf-8") == "first staged"
    assert second_staged.read_text(encoding="utf-8") == "second staged"
    assert not public.exists()
    assert (first_operation / "manifest.json").is_file()
    assert (second_operation / "manifest.json").is_file()


def test_invalid_operation_factory_and_base_exceptions_do_not_mutate(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store, session_id, _run_ids = _store_with_terminal_session(tmp_path)
    target = _write_audit(tmp_path, AUDIT_ID, "preserve")
    with pytest.raises(SessionDeletionError) as invalid:
        SessionDeletionService(
            tmp_path,
            store,
            operation_id_factory=lambda: "../invalid",
        ).delete(session_id)
    assert invalid.value.code == "session_delete_failed"
    assert target.read_text(encoding="utf-8") == "preserve"
    assert _operation_entries(tmp_path) == ()

    def interrupt(session: str) -> SessionDeletionManifest:
        raise SystemExit(9)

    monkeypatch.setattr(store, "get_session_deletion_manifest", interrupt)
    with pytest.raises(SystemExit) as interrupted:
        SessionDeletionService(tmp_path, store).delete(session_id)
    assert interrupted.value.code == 9
    assert target.read_text(encoding="utf-8") == "preserve"


@pytest.mark.parametrize("root_name", ("logs", "deletion-staging"))
def test_delete_rejects_non_directory_internal_roots(
    tmp_path: Path,
    root_name: str,
) -> None:
    store, session_id, _run_ids = _store_with_terminal_session(tmp_path)
    root = tmp_path / ".coding-agent" / root_name
    root.write_text("not a directory", encoding="utf-8")

    with pytest.raises(SessionDeletionError) as captured:
        SessionDeletionService(tmp_path, store).delete(session_id)

    assert captured.value.code == "session_delete_failed"
    assert root.read_text(encoding="utf-8") == "not a directory"
    assert store.session_exists(session_id) is True


def test_recovery_rejects_reparse_internal_directory(
    tmp_path: Path,
) -> None:
    store, _session_id, _run_ids = _store_with_terminal_session(tmp_path)
    service = SessionDeletionService(tmp_path, store)
    internal = tmp_path / ".coding-agent"
    target = tmp_path / "private-internal"
    internal.rename(target)
    try:
        internal.symlink_to(target, target_is_directory=True)
    except OSError as exc:
        target.rename(internal)
        pytest.fail(f"target Windows environment must allow this test: {exc}")

    with pytest.raises(SessionDeletionError) as captured:
        service.recover_pending()

    assert captured.value.code == "session_deletion_recovery_failed"
    assert (target / "sessions.sqlite3").is_file()

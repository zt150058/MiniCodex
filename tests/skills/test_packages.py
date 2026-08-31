from __future__ import annotations

import io
import stat
from pathlib import Path
import zipfile

import pytest

from coding_agent.skills import packages as skill_packages_module
from coding_agent.skills import catalog as skills_module
from coding_agent.skills.packages import SkillPackageError, SkillPackageInstaller
from coding_agent.skills.catalog import SkillSource, _EntryError


def _skill_bytes(skill_id: str = "review") -> bytes:
    return (
        "---\r\n"
        f"id: {skill_id}\r\n"
        "name: Review\r\n"
        "description: Review the current workspace.\r\n"
        "---\r\n"
        "Inspect carefully.\r\n"
    ).encode("utf-8")


def _skill_zip(
    skill_id: str = "review",
    *,
    compression: int = zipfile.ZIP_STORED,
    include_directory: bool = False,
    raw: bytes | None = None,
) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=compression) as archive:
        if include_directory:
            archive.writestr(f"{skill_id}/", b"")
        archive.writestr(f"{skill_id}/SKILL.md", raw or _skill_bytes(skill_id))
    return buffer.getvalue()


def _exact_size_skill_bytes() -> bytes:
    prefix = (
        "---\n"
        "id: review\n"
        "name: Review\n"
        "description: Review the current workspace.\n"
        "---\n"
    ).encode("utf-8")
    return prefix + b"x" * (65_536 - len(prefix))


def _zip_members(members: list[tuple[str, bytes | None]]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_STORED) as archive:
        for name, raw in members:
            archive.writestr(name, b"" if raw is None else raw)
    return buffer.getvalue()


def _patch_zip_u16(raw: bytes, offset: int, value: int) -> bytes:
    result = bytearray(raw)
    result[offset : offset + 2] = value.to_bytes(2, "little")
    return bytes(result)


def _patch_flags(raw: bytes, flags: int) -> bytes:
    central = raw.index(b"PK\x01\x02")
    result = _patch_zip_u16(raw, 6, flags)
    return _patch_zip_u16(result, central + 8, flags)


def _patch_compression(raw: bytes, compression: int) -> bytes:
    central = raw.index(b"PK\x01\x02")
    result = _patch_zip_u16(raw, 8, compression)
    return _patch_zip_u16(result, central + 10, compression)


def _replace_member_name(raw: bytes, replacement: bytes) -> bytes:
    original = b"review/SKILL.md"
    assert len(replacement) == len(original)
    assert raw.count(original) == 2
    return raw.replace(original, replacement)


@pytest.mark.parametrize(
    ("compression", "include_directory"),
    (
        (zipfile.ZIP_STORED, False),
        (zipfile.ZIP_STORED, True),
        (zipfile.ZIP_DEFLATED, False),
        (zipfile.ZIP_DEFLATED, True),
    ),
    ids=("stored-file", "stored-directory", "deflated-file", "deflated-directory"),
)
def test_inspect_accepts_one_declarative_skill_without_writing_catalog(
    tmp_path: Path,
    compression: int,
    include_directory: bool,
) -> None:
    root = tmp_path / ".coding-agent" / "skills"
    descriptor = SkillPackageInstaller(
        root,
        id_factory=lambda: "1" * 32,
    ).inspect(
        _skill_zip(
            compression=compression,
            include_directory=include_directory,
        )
    )

    assert descriptor.skill_id == "review"
    assert descriptor.name == "Review"
    assert descriptor.description == "Review the current workspace."
    assert descriptor.source is SkillSource.WORKSPACE
    assert descriptor.char_count == len("Inspect carefully.")
    assert not (tmp_path / ".coding-agent").exists()


def test_install_creates_missing_catalog_and_publishes_exact_skill_bytes(
    tmp_path: Path,
) -> None:
    root = tmp_path / ".coding-agent" / "skills"
    raw = _skill_bytes()

    descriptor = SkillPackageInstaller(
        root,
        id_factory=lambda: "1" * 32,
    ).install(_skill_zip(raw=raw))

    assert descriptor.skill_id == "review"
    assert (root / "review" / "SKILL.md").read_bytes() == raw
    assert not (root / (".import-" + "1" * 32)).exists()


def test_exact_member_and_archive_limits_are_accepted(tmp_path: Path) -> None:
    raw_definition = _exact_size_skill_bytes()
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_STORED) as archive:
        archive.writestr("review/SKILL.md", raw_definition)
    comment_size = 131_072 - len(buffer.getvalue())
    with zipfile.ZipFile(buffer, "a") as archive:
        assert 0 <= comment_size <= 65_535
        archive.comment = b"c" * comment_size
    raw_archive = buffer.getvalue()
    assert len(raw_archive) == 131_072

    descriptor = SkillPackageInstaller(tmp_path / "skills").inspect(raw_archive)

    assert descriptor.skill_id == "review"
    assert descriptor.char_count == len(raw_definition) - raw_definition.index(b"---\n", 4) - 4


@pytest.mark.parametrize(
    "archive",
    (
        b"",
        b"not a zip",
        _zip_members([("review/", None)]),
        _zip_members(
            [
                ("review/SKILL.md", _skill_bytes()),
                ("review/EXTRA.md", b"extra"),
            ]
        ),
        _zip_members(
            [
                ("review/SKILL.md", _skill_bytes()),
                ("other/SKILL.md", _skill_bytes("other")),
            ]
        ),
        _zip_members([("review/nested/SKILL.md", _skill_bytes())]),
        _zip_members([("review/./SKILL.md", _skill_bytes())]),
        _zip_members([("review//SKILL.md", _skill_bytes())]),
        _zip_members([("../review/SKILL.md", _skill_bytes())]),
        _zip_members([("/review/SKILL.md", _skill_bytes())]),
        _zip_members([("C:/review/SKILL.md", _skill_bytes())]),
        _zip_members([("review:stream/SKILL.md", _skill_bytes())]),
        _replace_member_name(_skill_zip(), b"review\\SKILL.md"),
        _zip_members([("review\x00/SKILL.md", _skill_bytes())]),
        _zip_members([("review/SKILL.mdAAAA", _skill_bytes())]).replace(
            b"review/SKILL.mdAAAA",
            b"review/SKILL.md\x00AAA",
        ),
        _skill_zip() + b"trailing",
        _skill_zip()[:-7],
        _skill_zip(raw=b"\xff"),
        _skill_zip(raw=b"x" * 65_537),
        _skill_zip(raw=_skill_bytes("other")),
    ),
    ids=(
        "empty",
        "not-zip",
        "missing-file",
        "extra-file",
        "multiple-root",
        "nested",
        "dot-segment",
        "empty-segment",
        "traversal",
        "absolute",
        "drive",
        "ads",
        "backslash",
        "control",
        "nul-suffix",
        "trailing",
        "truncated",
        "invalid-utf8",
        "actual-oversize",
        "id-mismatch",
    ),
)
def test_invalid_archive_shapes_are_rejected_before_catalog_write(
    tmp_path: Path,
    archive: bytes,
) -> None:
    root = tmp_path / ".coding-agent" / "skills"
    installer = SkillPackageInstaller(root, id_factory=lambda: "1" * 32)

    with pytest.raises(SkillPackageError) as captured:
        installer.install(archive)

    assert captured.value.code in {
        "invalid_skill_archive",
        "unsafe_skill_archive",
    }
    assert str(captured.value) == captured.value.code
    assert str(tmp_path) not in repr(captured.value)
    assert not (tmp_path / ".coding-agent").exists()


def test_duplicate_member_is_rejected_before_catalog_write(tmp_path: Path) -> None:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("review/SKILL.md", _skill_bytes())
        with pytest.warns(UserWarning):
            archive.writestr("review/SKILL.md", _skill_bytes())
    root = tmp_path / ".coding-agent" / "skills"

    with pytest.raises(SkillPackageError) as captured:
        SkillPackageInstaller(root).install(buffer.getvalue())

    assert captured.value.code == "invalid_skill_archive"
    assert not root.exists()


@pytest.mark.parametrize(
    "archive",
    (
        _patch_flags(_skill_zip(), 0x1),
        _patch_flags(_skill_zip(), 0x40),
        _patch_compression(_skill_zip(), 99),
    ),
    ids=("encrypted", "unsupported-flag", "unsupported-compression"),
)
def test_unsupported_zip_features_are_rejected(
    tmp_path: Path,
    archive: bytes,
) -> None:
    with pytest.raises(SkillPackageError) as captured:
        SkillPackageInstaller(tmp_path / "skills").inspect(archive)
    assert captured.value.code in {"invalid_skill_archive", "unsafe_skill_archive"}


def test_symlink_external_mode_is_rejected(tmp_path: Path) -> None:
    buffer = io.BytesIO()
    info = zipfile.ZipInfo("review/SKILL.md")
    info.create_system = 3
    info.external_attr = (stat.S_IFLNK | 0o777) << 16
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr(info, _skill_bytes())

    with pytest.raises(SkillPackageError) as captured:
        SkillPackageInstaller(tmp_path / "skills").inspect(buffer.getvalue())
    assert captured.value.code == "unsafe_skill_archive"


@pytest.mark.parametrize("kind", (stat.S_IFIFO, stat.S_IFCHR, stat.S_IFSOCK))
def test_non_regular_external_mode_is_rejected(tmp_path: Path, kind: int) -> None:
    buffer = io.BytesIO()
    info = zipfile.ZipInfo("review/SKILL.md")
    info.create_system = 3
    info.external_attr = (kind | 0o600) << 16
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr(info, _skill_bytes())
    with pytest.raises(SkillPackageError) as captured:
        SkillPackageInstaller(tmp_path / "skills").inspect(buffer.getvalue())
    assert captured.value.code == "unsafe_skill_archive"


@pytest.mark.parametrize("dos_attributes", (0x40, 0x10))
def test_windows_device_and_file_directory_attributes_are_rejected(
    tmp_path: Path,
    dos_attributes: int,
) -> None:
    buffer = io.BytesIO()
    info = zipfile.ZipInfo("review/SKILL.md")
    info.create_system = 0
    info.external_attr = dos_attributes
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr(info, _skill_bytes())

    with pytest.raises(SkillPackageError) as captured:
        SkillPackageInstaller(tmp_path / "skills").inspect(buffer.getvalue())

    assert captured.value.code == "unsafe_skill_archive"


def test_crc_damage_is_rejected_without_leaking_payload(tmp_path: Path) -> None:
    archive = bytearray(_skill_zip())
    payload_position = archive.index(_skill_bytes())
    archive[payload_position] ^= 0x01

    with pytest.raises(SkillPackageError) as captured:
        SkillPackageInstaller(tmp_path / "skills").inspect(bytes(archive))

    assert captured.value.code == "invalid_skill_archive"
    assert "Inspect carefully" not in repr(captured.value)


def test_raw_archive_first_byte_over_limit_has_exact_error(tmp_path: Path) -> None:
    with pytest.raises(SkillPackageError) as captured:
        SkillPackageInstaller(tmp_path / "skills").inspect(b"x" * 131_073)
    assert captured.value.code == "skill_archive_too_large"


@pytest.mark.parametrize("archive", (bytearray(), memoryview(b"zip"), "zip"))
def test_archive_requires_exact_bytes_type(tmp_path: Path, archive: object) -> None:
    with pytest.raises(SkillPackageError) as captured:
        SkillPackageInstaller(tmp_path / "skills").inspect(archive)  # type: ignore[arg-type]
    assert captured.value.code == "invalid_skill_archive"


def test_existing_skill_is_preserved_and_rejected(tmp_path: Path) -> None:
    root = tmp_path / "skills"
    destination = root / "review"
    destination.mkdir(parents=True)
    winner = destination / "SKILL.md"
    winner.write_text("winner", encoding="utf-8")

    with pytest.raises(SkillPackageError) as captured:
        SkillPackageInstaller(root).install(_skill_zip())

    assert captured.value.code == "skill_already_exists"
    assert winner.read_text(encoding="utf-8") == "winner"


def test_staging_collision_is_preserved(tmp_path: Path) -> None:
    root = tmp_path / "skills"
    staging = root / (".import-" + "1" * 32)
    staging.mkdir(parents=True)

    with pytest.raises(SkillPackageError) as captured:
        SkillPackageInstaller(
            root,
            id_factory=lambda: "1" * 32,
        ).install(_skill_zip())

    assert captured.value.code == "skill_already_exists"
    assert staging.is_dir()


def test_invalid_operation_id_fails_before_catalog_write(tmp_path: Path) -> None:
    root = tmp_path / "skills"
    with pytest.raises(SkillPackageError) as captured:
        SkillPackageInstaller(root, id_factory=lambda: "../unsafe").install(
            _skill_zip()
        )
    assert captured.value.code == "skill_install_failed"
    assert not root.exists()


def test_operation_id_factory_error_is_stable_and_private(tmp_path: Path) -> None:
    root = tmp_path / "skills"

    def fail() -> str:
        raise RuntimeError(f"private factory failure at {tmp_path}")

    with pytest.raises(SkillPackageError) as captured:
        SkillPackageInstaller(root, id_factory=fail).install(_skill_zip())

    assert captured.value.code == "skill_install_failed"
    assert str(tmp_path) not in repr(captured.value)
    assert not root.exists()


def test_exclusive_file_create_failure_removes_only_owned_empty_staging(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "skills"
    staging_file = root / (".import-" + "1" * 32) / "SKILL.md"
    real_open = Path.open

    def denied_open(path: Path, *args: object, **kwargs: object) -> object:
        if path == staging_file:
            raise PermissionError
        return real_open(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", denied_open)
    with pytest.raises(SkillPackageError) as captured:
        SkillPackageInstaller(root, id_factory=lambda: "1" * 32).install(
            _skill_zip()
        )

    assert captured.value.code == "skill_install_failed"
    assert not staging_file.parent.exists()
    assert not (root / "review").exists()


def test_reparse_failure_cleans_owned_staging(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "skills"

    def fail_reparse(*args: object, **kwargs: object) -> object:
        raise _EntryError("skill_file_not_utf8")

    monkeypatch.setattr(skill_packages_module, "_read_definition", fail_reparse)
    with pytest.raises(SkillPackageError) as captured:
        SkillPackageInstaller(root, id_factory=lambda: "1" * 32).install(
            _skill_zip()
        )

    assert captured.value.code == "skill_install_failed"
    assert not (root / (".import-" + "1" * 32)).exists()
    assert not (root / "review").exists()


def test_reparsed_descriptor_mismatch_cleans_owned_staging(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "skills"
    changed = skills_module._parse_skill_document(
        _skill_bytes().replace(b"Inspect carefully.", b"Changed safely."),
        SkillSource.WORKSPACE,
        "review",
    )
    monkeypatch.setattr(skill_packages_module, "_read_definition", lambda *args: changed)

    with pytest.raises(SkillPackageError) as captured:
        SkillPackageInstaller(root, id_factory=lambda: "1" * 32).install(
            _skill_zip()
        )

    assert captured.value.code == "skill_install_failed"
    assert not (root / (".import-" + "1" * 32)).exists()
    assert not (root / "review").exists()


def test_rename_race_preserves_winner_and_cleans_owned_staging(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "skills"
    staging = root / (".import-" + "1" * 32)
    destination = root / "review"
    real_rename = Path.rename

    def racing_rename(path: Path, target: Path) -> Path:
        if path == staging:
            destination.mkdir()
            (destination / "SKILL.md").write_text("winner", encoding="utf-8")
            raise FileExistsError
        return real_rename(path, target)

    monkeypatch.setattr(Path, "rename", racing_rename)
    with pytest.raises(SkillPackageError) as captured:
        SkillPackageInstaller(root, id_factory=lambda: "1" * 32).install(
            _skill_zip()
        )

    assert captured.value.code == "skill_already_exists"
    assert (destination / "SKILL.md").read_text(encoding="utf-8") == "winner"
    assert not staging.exists()


def test_unexpected_staging_content_is_not_recursively_removed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "skills"
    staging = root / (".import-" + "1" * 32)

    def add_unexpected_file(*args: object, **kwargs: object) -> object:
        (staging / "unexpected").write_text("preserve", encoding="utf-8")
        raise _EntryError("invalid_skill_front_matter")

    monkeypatch.setattr(skill_packages_module, "_read_definition", add_unexpected_file)
    with pytest.raises(SkillPackageError) as captured:
        SkillPackageInstaller(root, id_factory=lambda: "1" * 32).install(
            _skill_zip()
        )

    assert captured.value.code == "skill_install_failed"
    assert (staging / "unexpected").read_text(encoding="utf-8") == "preserve"
    assert not (staging / "SKILL.md").exists()


def test_reparse_catalog_root_and_destination_are_rejected(
    tmp_path: Path,
) -> None:
    target = tmp_path / "target"
    target.mkdir()
    linked_root = tmp_path / "linked-root"
    try:
        linked_root.symlink_to(target, target_is_directory=True)
    except OSError as exc:
        pytest.fail(f"target Windows environment must allow this test: {exc}")
    with pytest.raises(SkillPackageError) as root_error:
        SkillPackageInstaller(linked_root).install(_skill_zip())
    assert root_error.value.code == "skill_install_failed"
    assert list(target.iterdir()) == []

    root = tmp_path / "skills"
    root.mkdir()
    destination = root / "review"
    destination.symlink_to(target, target_is_directory=True)
    with pytest.raises(SkillPackageError) as destination_error:
        SkillPackageInstaller(root).install(_skill_zip())
    assert destination_error.value.code == "skill_install_failed"


def test_reparse_staging_collision_is_rejected_without_touching_target(
    tmp_path: Path,
) -> None:
    root = tmp_path / "skills"
    root.mkdir()
    target = tmp_path / "private-target"
    target.mkdir()
    marker = target / "private"
    marker.write_text("secret", encoding="utf-8")
    staging = root / (".import-" + "1" * 32)
    try:
        staging.symlink_to(target, target_is_directory=True)
    except OSError as exc:
        pytest.fail(f"target Windows environment must allow this test: {exc}")

    with pytest.raises(SkillPackageError) as captured:
        SkillPackageInstaller(root, id_factory=lambda: "1" * 32).install(
            _skill_zip()
        )

    assert captured.value.code == "skill_install_failed"
    assert marker.read_text(encoding="utf-8") == "secret"
    assert staging.is_symlink()


def test_cleanup_does_not_follow_staging_replaced_by_directory_symlink(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "skills"
    staging = root / (".import-" + "1" * 32)
    outside = tmp_path / "outside"
    outside.mkdir()
    marker = outside / "SKILL.md"
    marker.write_text("private", encoding="utf-8")

    def swap_before_cleanup(*args: object, **kwargs: object) -> object:
        (staging / "SKILL.md").unlink()
        staging.rmdir()
        staging.symlink_to(outside, target_is_directory=True)
        raise _EntryError("invalid_skill_front_matter")

    monkeypatch.setattr(skill_packages_module, "_read_definition", swap_before_cleanup)
    with pytest.raises(SkillPackageError) as captured:
        SkillPackageInstaller(root, id_factory=lambda: "1" * 32).install(
            _skill_zip()
        )

    assert captured.value.code == "skill_install_failed"
    assert marker.read_text(encoding="utf-8") == "private"

from __future__ import annotations

import hashlib
import os
from pathlib import Path
import subprocess
import sys

import pytest

from coding_agent.skills import catalog as skills_module
from coding_agent.skills.catalog import (
    RunSkillSnapshotMetadata,
    SkillCatalog,
    SkillCatalogError,
    SkillDescriptor,
    SkillSource,
)


def test_parse_skill_document_matches_catalog_discovery(tmp_path: Path) -> None:
    raw = (
        b"---\r\n"
        b"id: review\r\n"
        b"name: Review\r\n"
        b"description: Review safely.\r\n"
        b"---\r\n"
        b"first\r\nsecond\r\n"
    )
    parsed = skills_module._parse_skill_document(
        raw,
        SkillSource.WORKSPACE,
        "review",
    )
    root = tmp_path / "workspace"
    directory = root / "review"
    directory.mkdir(parents=True)
    (directory / "SKILL.md").write_bytes(raw)
    discovered = SkillCatalog(
        user_root=tmp_path / "missing-user",
        workspace_root=root,
    ).discover().skills[0]

    assert parsed.instructions == "first\nsecond"
    assert parsed.descriptor == discovered
    assert parsed.descriptor.sha256 == hashlib.sha256(b"first\nsecond").hexdigest()
    assert parsed.descriptor.char_count == len("first\nsecond")


@pytest.mark.parametrize(
    ("raw", "entry_name", "code"),
    [
        (b"\xff", "review", "skill_file_not_utf8"),
        (b"x" * 65_537, "review", "skill_file_too_large"),
        (
            b"---\nid: review\nname: Review\ndescription: Safe\n---\nbody\x00",
            "review",
            "invalid_skill_instructions",
        ),
        (b"id: review\nbody", "review", "invalid_skill_front_matter"),
        (
            b"---\nid: other\nname: Review\ndescription: Safe\n---\nbody",
            "review",
            "skill_id_mismatch",
        ),
        (
            b"---\nid: review\nname: Review\ndescription: Safe\n---\n \n",
            "review",
            "empty_skill_instructions",
        ),
    ],
    ids=("utf8", "too-large", "control", "front-matter", "id", "body"),
)
def test_parse_skill_document_preserves_exact_entry_error_codes(
    raw: bytes,
    entry_name: str,
    code: str,
) -> None:
    with pytest.raises(skills_module._EntryError) as captured:
        skills_module._parse_skill_document(raw, SkillSource.WORKSPACE, entry_name)

    assert captured.value.code == code


def write_skill(
    root: Path,
    skill_id: str,
    body: str,
    *,
    name: str | None = None,
    description: str = "Deterministic local instructions.",
    bom: bool = False,
    newline: str = "\n",
) -> Path:
    directory = root / skill_id
    directory.mkdir(parents=True, exist_ok=True)
    text = newline.join(
        (
            "---",
            f"id: {skill_id}",
            f"name: {name or skill_id.replace('-', ' ').title()}",
            f"description: {description}",
            "---",
            body,
        )
    )
    encoded = text.encode("utf-8")
    if bom:
        encoded = b"\xef\xbb\xbf" + encoded
    path = directory / "SKILL.md"
    path.write_bytes(encoded)
    return path


def test_missing_catalog_roots_are_empty(tmp_path: Path) -> None:
    catalog = SkillCatalog(
        user_root=tmp_path / "missing-user",
        workspace_root=tmp_path / "missing-workspace",
    )
    view = catalog.discover()
    assert view.skills == ()
    assert view.diagnostics == ()
    assert view.usable is True


def test_valid_skills_are_normalized_hashed_and_stably_sorted(
    tmp_path: Path,
) -> None:
    user_root = tmp_path / "user"
    workspace_root = tmp_path / "workspace"
    write_skill(workspace_root, "zeta", "line one\r\nline two\r\n")
    write_skill(user_root, "alpha", "  first\rsecond  ", bom=True)
    catalog = SkillCatalog(
        user_root=user_root,
        workspace_root=workspace_root,
    )
    first = catalog.discover()
    second = catalog.discover()
    assert first == second
    assert [item.skill_id for item in first.skills] == ["alpha", "zeta"]
    assert [item.source for item in first.skills] == [
        SkillSource.USER,
        SkillSource.WORKSPACE,
    ]
    assert first.skills[0].char_count == len("first\nsecond")
    assert first.skills[0].sha256 == hashlib.sha256(
        b"first\nsecond"
    ).hexdigest()
    assert first.diagnostics == ()
    assert first.usable is True


def test_newline_normalization_is_exact_and_preserves_unicode_nel(
    tmp_path: Path,
) -> None:
    root = tmp_path / "user"
    write_skill(root, "unicode-lines", "first\u0085second\r\nthird\rfourth")
    descriptor = SkillCatalog(
        user_root=root,
        workspace_root=tmp_path / "workspace",
    ).discover().skills[0]
    normalized = "first\u0085second\nthird\nfourth"
    assert descriptor.char_count == len(normalized)
    assert descriptor.sha256 == hashlib.sha256(normalized.encode("utf-8")).hexdigest()


@pytest.mark.parametrize(
    ("entry_name", "content", "expected_code"),
    (
        (
            "Bad_ID",
            b"---\nid: Bad_ID\nname: Bad\ndescription: bad\n---\nbody",
            "invalid_entry_name",
        ),
        ("missing-file", None, "missing_skill_file"),
        (
            "bad-front",
            b"id: bad-front\nbody",
            "invalid_skill_front_matter",
        ),
        (
            "missing-field",
            b"---\nid: missing-field\nname: Missing\n---\nbody",
            "invalid_skill_front_matter",
        ),
        (
            "empty-name",
            b"---\nid: empty-name\nname: \ndescription: x\n---\nbody",
            "invalid_skill_metadata",
        ),
        (
            "long-name",
            (
                "---\nid: long-name\nname: "
                + "n" * 81
                + "\ndescription: x\n---\nbody"
            ).encode("utf-8"),
            "invalid_skill_metadata",
        ),
        (
            "long-description",
            (
                "---\nid: long-description\nname: Long\ndescription: "
                + "d" * 241
                + "\n---\nbody"
            ).encode("utf-8"),
            "invalid_skill_metadata",
        ),
        (
            "multiline",
            b"---\nid: multiline\nname: Multi\ndescription: first\n  second\n---\nbody",
            "invalid_skill_front_matter",
        ),
        (
            "unknown",
            b"---\nid: unknown\nname: Unknown\ndescription: x\nversion: 1\n---\nbody",
            "invalid_skill_front_matter",
        ),
        (
            "duplicate",
            b"---\nid: duplicate\nname: One\nname: Two\ndescription: x\n---\nbody",
            "invalid_skill_front_matter",
        ),
        (
            "mismatch",
            b"---\nid: other\nname: Other\ndescription: x\n---\nbody",
            "skill_id_mismatch",
        ),
        (
            "empty-body",
            b"---\nid: empty-body\nname: Empty\ndescription: x\n---\n \n",
            "empty_skill_instructions",
        ),
        (
            "control",
            b"---\nid: control\nname: Control\ndescription: x\n---\nbody\x00",
            "invalid_skill_instructions",
        ),
        (
            "vt-control",
            b"---\nid: vt-control\nname: Control\ndescription: x\n---\nbody\x0bnext",
            "invalid_skill_instructions",
        ),
        (
            "ff-control",
            b"---\nid: ff-control\nname: Control\ndescription: x\n---\nbody\x0cnext",
            "invalid_skill_instructions",
        ),
        (
            "del-control",
            b"---\nid: del-control\nname: Control\ndescription: x\n---\nbody\x7fnext",
            "invalid_skill_instructions",
        ),
    ),
)
def test_malformed_entry_is_isolated_with_safe_diagnostic(
    tmp_path: Path,
    entry_name: str,
    content: bytes | None,
    expected_code: str,
) -> None:
    user_root = tmp_path / "user"
    write_skill(user_root, "valid", "safe body")
    directory = user_root / entry_name
    directory.mkdir(parents=True, exist_ok=True)
    if content is not None:
        (directory / "SKILL.md").write_bytes(content)
    view = SkillCatalog(
        user_root=user_root,
        workspace_root=tmp_path / "workspace",
    ).discover()
    assert [item.skill_id for item in view.skills] == ["valid"]
    assert [(item.code, item.source, item.entry_name) for item in view.diagnostics] == [
        (expected_code, SkillSource.USER, entry_name)
    ]
    rendered = repr(view.diagnostics)
    assert str(tmp_path) not in rendered
    assert "safe body" not in rendered
    assert view.usable is True


def test_invalid_utf8_and_first_byte_over_limit_are_rejected(
    tmp_path: Path,
) -> None:
    root = tmp_path / "user"
    exact_directory = root / "exact"
    exact_directory.mkdir(parents=True)
    exact_prefix = b"---\nid: exact\nname: Exact\ndescription: x\n---\n"
    (exact_directory / "SKILL.md").write_bytes(
        exact_prefix + b"x" * (65_536 - len(exact_prefix))
    )
    for skill_id, raw in (
        ("bad-utf8", b"\xff\xfe"),
        ("too-large", b"x" * 65_537),
    ):
        directory = root / skill_id
        directory.mkdir(parents=True)
        (directory / "SKILL.md").write_bytes(raw)
    view = SkillCatalog(
        user_root=root,
        workspace_root=tmp_path / "workspace",
    ).discover()
    assert [item.skill_id for item in view.skills] == ["exact"]
    assert [(item.entry_name, item.code) for item in view.diagnostics] == [
        ("bad-utf8", "skill_file_not_utf8"),
        ("too-large", "skill_file_too_large"),
    ]


def test_skill_id_boundaries_are_exact(tmp_path: Path) -> None:
    root = tmp_path / "user"
    valid_id = "a" * 64
    write_skill(root, valid_id, "valid maximum id")
    for invalid_id in ("-leading", "trailing-", "a" * 65):
        directory = root / invalid_id
        directory.mkdir(parents=True)
        (directory / "SKILL.md").write_text(
            "---\n"
            f"id: {invalid_id}\n"
            "name: Boundary\n"
            "description: x\n"
            "---\n"
            "body",
            encoding="utf-8",
        )
    view = SkillCatalog(
        user_root=root,
        workspace_root=tmp_path / "workspace",
    ).discover()
    assert [item.skill_id for item in view.skills] == [valid_id]
    assert [item.entry_name for item in view.diagnostics] == [
        "-leading",
        "a" * 65,
        "trailing-",
    ]
    assert all(item.code == "invalid_entry_name" for item in view.diagnostics)


def test_public_skill_metadata_types_reject_invalid_construction() -> None:
    with pytest.raises(TypeError):
        SkillDescriptor(
            "valid",
            "Valid",
            "safe",
            "user",  # type: ignore[arg-type]
            "0" * 64,
            1,
        )
    with pytest.raises(ValueError):
        SkillDescriptor(
            "valid",
            "Valid",
            "safe",
            SkillSource.USER,
            "not-a-hash",
            1,
        )
    with pytest.raises(ValueError):
        RunSkillSnapshotMetadata(
            "valid",
            SkillSource.USER,
            "0" * 64,
            0,
        )


def test_duplicate_id_across_sources_has_no_precedence(tmp_path: Path) -> None:
    user_root = tmp_path / "user"
    workspace_root = tmp_path / "workspace"
    write_skill(user_root, "review", "user body")
    write_skill(workspace_root, "review", "workspace body")
    catalog = SkillCatalog(user_root=user_root, workspace_root=workspace_root)
    view = catalog.discover()
    assert view.skills == ()
    assert view.usable is False
    assert [(item.source, item.entry_name, item.code) for item in view.diagnostics] == [
        (SkillSource.USER, "review", "duplicate_skill_id"),
        (SkillSource.WORKSPACE, "review", "duplicate_skill_id"),
    ]
    with pytest.raises(SkillCatalogError) as captured:
        catalog.resolve(("review",))
    assert captured.value.code == "duplicate_skill_id"
    assert str(captured.value) == "duplicate_skill_id"
    assert str(tmp_path) not in repr(captured.value)


def test_malformed_same_id_across_sources_has_no_precedence(
    tmp_path: Path,
) -> None:
    user_root = tmp_path / "user"
    workspace_root = tmp_path / "workspace"
    write_skill(user_root, "review", "trusted user body")
    malformed = workspace_root / "review" / "SKILL.md"
    malformed.parent.mkdir(parents=True)
    malformed.write_text("not front matter", encoding="utf-8")
    catalog = SkillCatalog(user_root=user_root, workspace_root=workspace_root)

    view = catalog.discover()

    assert view.skills == ()
    assert view.usable is False
    assert [
        (item.source, item.entry_name, item.code)
        for item in view.diagnostics
    ] == [
        (SkillSource.USER, "review", "duplicate_skill_id"),
        (SkillSource.WORKSPACE, "review", "duplicate_skill_id"),
        (SkillSource.WORKSPACE, "review", "invalid_skill_front_matter"),
    ]
    with pytest.raises(SkillCatalogError) as captured:
        catalog.resolve(("review",))
    assert captured.value.code == "duplicate_skill_id"


def test_unsafe_same_id_across_sources_has_no_precedence(tmp_path: Path) -> None:
    user_root = tmp_path / "user"
    workspace_root = tmp_path / "workspace"
    target_root = tmp_path / "target"
    write_skill(user_root, "review", "trusted user body")
    target = write_skill(target_root, "review", "private target body").parent
    link = workspace_root / "review"
    link.parent.mkdir(parents=True)
    link.symlink_to(target, target_is_directory=True)
    catalog = SkillCatalog(user_root=user_root, workspace_root=workspace_root)

    view = catalog.discover()

    assert view.skills == ()
    assert view.usable is False
    assert [
        (item.source, item.entry_name, item.code)
        for item in view.diagnostics
    ] == [
        (SkillSource.USER, "review", "duplicate_skill_id"),
        (SkillSource.WORKSPACE, "review", "duplicate_skill_id"),
        (SkillSource.WORKSPACE, "review", "unsafe_skill_path"),
    ]
    with pytest.raises(SkillCatalogError) as captured:
        catalog.resolve(("review",))
    assert captured.value.code == "duplicate_skill_id"
    assert "private target body" not in repr(view)
    assert str(target) not in repr(view)


def test_unreadable_same_id_candidate_has_no_precedence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user_root = tmp_path / "user"
    workspace_root = tmp_path / "workspace"
    write_skill(user_root, "review", "trusted user body")
    workspace_entry = write_skill(
        workspace_root,
        "review",
        "unreadable workspace body",
    ).parent
    real_lstat = os.lstat

    def guarded_lstat(path: object) -> os.stat_result:
        if Path(path) == workspace_entry:
            raise PermissionError
        return real_lstat(path)

    monkeypatch.setattr(os, "lstat", guarded_lstat)
    catalog = SkillCatalog(user_root=user_root, workspace_root=workspace_root)

    view = catalog.discover()

    assert view.skills == ()
    assert view.usable is False
    assert [
        (item.source, item.entry_name, item.code)
        for item in view.diagnostics
    ] == [
        (SkillSource.USER, "review", "duplicate_skill_id"),
        (SkillSource.WORKSPACE, "review", "duplicate_skill_id"),
        (SkillSource.WORKSPACE, "review", "unsafe_skill_path"),
    ]
    with pytest.raises(SkillCatalogError) as captured:
        catalog.resolve(("review",))
    assert captured.value.code == "duplicate_skill_id"


def test_resolve_preserves_explicit_order_and_hides_instruction_text(
    tmp_path: Path,
) -> None:
    user_root = tmp_path / "user"
    workspace_root = tmp_path / "workspace"
    write_skill(user_root, "first", "private first")
    write_skill(workspace_root, "second", "private second")
    catalog = SkillCatalog(user_root=user_root, workspace_root=workspace_root)
    assert catalog.resolve(()) is None
    bundle = catalog.resolve(("second", "first"))
    assert bundle is not None
    assert [item.descriptor.skill_id for item in bundle.items] == [
        "second",
        "first",
    ]
    assert bundle.text == (
        "### Skill: second — Second\nprivate second\n\n"
        "### Skill: first — First\nprivate first"
    )
    assert bundle.sha256 == hashlib.sha256(bundle.text.encode("utf-8")).hexdigest()
    assert bundle.char_count == len(bundle.text)
    rendered = repr(bundle)
    assert "private first" not in rendered
    assert "private second" not in rendered
    with pytest.raises(Exception):
        bundle.items[0].instructions = "changed"  # type: ignore[misc]


@pytest.mark.parametrize(
    ("selection", "code"),
    (
        (["valid"], "invalid_skill_selection"),
        (("Bad_ID",), "invalid_skill_selection"),
        (("../valid",), "invalid_skill_selection"),
        (("C:\\valid",), "invalid_skill_selection"),
        (("valid:stream",), "invalid_skill_selection"),
        (("valid", "valid"), "duplicate_skill_selection"),
        (("missing",), "selected_skill_unavailable"),
    ),
)
def test_invalid_selection_has_stable_error(
    tmp_path: Path,
    selection: object,
    code: str,
) -> None:
    root = tmp_path / "user"
    write_skill(root, "valid", "body")
    catalog = SkillCatalog(user_root=root, workspace_root=tmp_path / "workspace")
    with pytest.raises(SkillCatalogError) as captured:
        catalog.resolve(selection)  # type: ignore[arg-type]
    assert captured.value.code == code


def test_combined_limit_accepts_exact_limit_and_rejects_first_byte_over(
    tmp_path: Path,
) -> None:
    root = tmp_path / "user"
    first_body = "a" * 128
    write_skill(root, "first", first_body)
    first_section = "### Skill: first — First\n" + first_body
    second_prefix = "### Skill: second — Second\n"
    second_body_size = 65_536 - len(
        (first_section + "\n\n" + second_prefix).encode("utf-8")
    )
    write_skill(root, "second", "b" * second_body_size)
    assert (root / "second" / "SKILL.md").stat().st_size <= 65_536
    catalog = SkillCatalog(user_root=root, workspace_root=tmp_path / "workspace")
    exact = catalog.resolve(("first", "second"))
    assert exact is not None
    assert len(exact.text.encode("utf-8")) == 65_536
    write_skill(root, "second", "b" * (second_body_size + 1))
    with pytest.raises(SkillCatalogError) as captured:
        catalog.resolve(("first", "second"))
    assert captured.value.code == "skill_selection_too_large"


def test_symlink_skill_directory_is_rejected_without_reading_target(
    tmp_path: Path,
) -> None:
    target_root = tmp_path / "target-root"
    target_file = write_skill(target_root, "review", "private target body")
    user_root = tmp_path / "user"
    user_root.mkdir()
    link = user_root / "review"
    try:
        link.symlink_to(target_file.parent, target_is_directory=True)
    except OSError as exc:
        pytest.fail(f"target Windows environment must allow this test: {exc}")
    view = SkillCatalog(
        user_root=user_root,
        workspace_root=tmp_path / "workspace",
    ).discover()
    assert view.skills == ()
    assert [(item.entry_name, item.code) for item in view.diagnostics] == [
        ("review", "unsafe_skill_path")
    ]
    assert "private target body" not in repr(view)
    assert str(tmp_path) not in repr(view)


def test_symlink_skill_file_is_rejected_without_reading_target(
    tmp_path: Path,
) -> None:
    target = tmp_path / "private-target.md"
    target.write_text("private file target", encoding="utf-8")
    directory = tmp_path / "user" / "review"
    directory.mkdir(parents=True)
    link = directory / "SKILL.md"
    try:
        link.symlink_to(target)
    except OSError as exc:
        pytest.fail(f"target Windows environment must allow this test: {exc}")
    view = SkillCatalog(
        user_root=tmp_path / "user",
        workspace_root=tmp_path / "workspace",
    ).discover()
    assert [(item.entry_name, item.code) for item in view.diagnostics] == [
        ("review", "unsafe_skill_path")
    ]
    assert "private file target" not in repr(view)


def test_junction_catalog_root_is_rejected_without_reading_target(
    tmp_path: Path,
) -> None:
    target = tmp_path / "junction-target"
    write_skill(target, "review", "private junction body")
    junction = tmp_path / "junction-user"
    completed = subprocess.run(
        [
            "cmd.exe",
            "/d",
            "/c",
            "mklink",
            "/J",
            str(junction.resolve(strict=False)),
            str(target.resolve(strict=True)),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    try:
        view = SkillCatalog(
            user_root=junction,
            workspace_root=tmp_path / "workspace",
        ).discover()
        assert view.skills == ()
        assert [
            (item.source, item.entry_name, item.code)
            for item in view.diagnostics
        ] == [
            (SkillSource.USER, "<catalog>", "catalog_root_unavailable")
        ]
        assert "private junction body" not in repr(view)
        assert str(target) not in repr(view)
    finally:
        os.rmdir(junction)


def test_present_non_directory_root_has_safe_diagnostic(tmp_path: Path) -> None:
    user_root = tmp_path / "user-file"
    user_root.write_text("private root content", encoding="utf-8")
    view = SkillCatalog(
        user_root=user_root,
        workspace_root=tmp_path / "workspace",
    ).discover()
    assert view.skills == ()
    assert [(item.source, item.entry_name, item.code) for item in view.diagnostics] == [
        (SkillSource.USER, "<catalog>", "catalog_root_unavailable")
    ]
    assert view.usable is False
    assert "private root content" not in repr(view)


def test_from_environment_uses_exact_localappdata_root(tmp_path: Path) -> None:
    local_app_data = tmp_path / "local-app-data"
    user_skills = local_app_data / "MiniCodex" / "skills"
    write_skill(user_skills, "review", "user review")
    catalog = SkillCatalog.from_environment(
        tmp_path,
        environ={"LOCALAPPDATA": str(local_app_data)},
    )
    view = catalog.discover()
    assert [(item.skill_id, item.source) for item in view.skills] == [
        ("review", SkillSource.USER)
    ]
    assert view.diagnostics == ()
    assert view.usable is True


def test_missing_localappdata_makes_nonempty_selection_unavailable(
    tmp_path: Path,
) -> None:
    workspace_skills = tmp_path / ".coding-agent" / "skills"
    write_skill(workspace_skills, "review", "workspace review")
    catalog = SkillCatalog.from_environment(tmp_path, environ={})
    view = catalog.discover()
    assert [item.skill_id for item in view.skills] == ["review"]
    assert [item.source for item in view.skills] == [SkillSource.WORKSPACE]
    assert [(item.source, item.entry_name, item.code) for item in view.diagnostics] == [
        (SkillSource.USER, "<catalog>", "catalog_root_unavailable")
    ]
    assert view.usable is False
    assert catalog.resolve(()) is None
    with pytest.raises(SkillCatalogError) as captured:
        catalog.resolve(("review",))
    assert captured.value.code == "skill_catalog_unavailable"


def test_both_unavailable_roots_reject_nonempty_selection(tmp_path: Path) -> None:
    workspace_root = tmp_path / ".coding-agent" / "skills"
    workspace_root.parent.mkdir(parents=True)
    workspace_root.write_text("not a catalog", encoding="utf-8")
    catalog = SkillCatalog.from_environment(tmp_path, environ={})
    view = catalog.discover()
    assert view.skills == ()
    assert view.usable is False
    assert [item.code for item in view.diagnostics] == [
        "catalog_root_unavailable",
        "catalog_root_unavailable",
    ]
    with pytest.raises(SkillCatalogError) as captured:
        catalog.resolve(("missing",))
    assert captured.value.code == "skill_catalog_unavailable"


def test_skill_and_session_modules_import_without_provider_or_network(
    tmp_path: Path,
) -> None:
    script = """
import builtins
import importlib
import os
import socket

for name in ("OPENAI_API_KEY", "CHAT_COMPLETIONS_API_KEY"):
    os.environ.pop(name, None)
forbidden = {"openai", "httpx", "requests"}
real_import = builtins.__import__

def guarded_import(name, *args, **kwargs):
    if name.split(".")[0] in forbidden:
        raise AssertionError(name)
    return real_import(name, *args, **kwargs)

builtins.__import__ = guarded_import
socket.socket = lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("network"))
for name in (
    "coding_agent.skills.catalog",
    "coding_agent.sessions.session",
    "coding_agent.sessions.session_store",
    "coding_agent.sessions.session_runtime",
    "coding_agent.sessions.session_controller",
):
    importlib.import_module(name)
"""
    completed = subprocess.run(
        [sys.executable, "-c", script],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr

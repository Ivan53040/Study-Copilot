"""Safety tests: the copilot must only write to StudyCopilot/ and never read secrets."""

from __future__ import annotations

import pytest

from app.security.paths import (
    PathSecurityError,
    assert_writable,
    is_denied,
    is_readable,
    is_writable,
)


def test_write_allowed_inside_studycopilot(settings):
    target = settings.output_root / "Generated Notes" / "week1.md"
    assert is_writable(target, settings)
    assert assert_writable(target, settings) == target.resolve()


def test_write_blocked_outside_studycopilot(settings):
    target = settings.vault.root / "REIT6811 - Research Methods" / "hack.md"
    assert not is_writable(target, settings)
    with pytest.raises(PathSecurityError):
        assert_writable(target, settings)


def test_write_blocked_via_path_traversal(settings):
    target = settings.output_root / ".." / ".." / "secret.md"
    assert not is_writable(target, settings)


def test_env_file_is_denied(settings):
    env = settings.vault.root / ".env"
    assert is_denied(env, settings)
    assert not is_readable(env, settings)


def test_obsidian_dir_is_denied(settings):
    plugin = settings.vault.root / ".obsidian" / "plugins" / "config.json"
    assert not is_readable(plugin, settings)


def test_trash_dir_is_denied_by_default(settings):
    # .trash isn't in this fixture's denied_paths — the defensive default must
    # still block it (the note editor promises .trash is never touched).
    trashed = settings.vault.root / ".trash" / "old note.md"
    assert is_denied(trashed, settings)
    assert not is_readable(trashed, settings)


def test_course_note_is_readable(settings):
    note = (
        settings.vault.root
        / "REIT6811 - Research Methods"
        / "REIT6811_Week1_Revision_Notes.md"
    )
    assert is_readable(note, settings)


def test_external_source_is_readable(settings):
    src = settings.external_sources[0].path / "paper.pdf"
    assert is_readable(src, settings)


def test_unlisted_vault_folder_not_readable(settings):
    other = settings.vault.root / "Personal Diary" / "private.md"
    assert not is_readable(other, settings)

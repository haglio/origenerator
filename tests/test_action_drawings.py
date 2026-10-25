"""Fixture values are fabricated throughout (see CLAUDE.md)."""
from __future__ import annotations

from origenerator.action_drawings import (
    DRAWINGS_DIR,
    OWN_DRAWINGS_DIR,
    drawing_for,
    drawing_path,
)


def test_a_states_drawing_sits_under_the_librarys_own_folder_named_for_it():
    assert drawing_path("state one") == DRAWINGS_DIR / "state-one.png"
    # The shapes the real names come in: two states in one, and a hyphen.
    assert drawing_path("Alpha, Beta") == DRAWINGS_DIR / "alpha-beta.png"
    assert drawing_path("no-hands gamma") == DRAWINGS_DIR / "no-hands-gamma.png"


def test_a_state_with_no_drawing_installed_answers_with_none(tmp_path, monkeypatch):
    monkeypatch.setattr("origenerator.action_drawings.DRAWINGS_DIR", tmp_path)

    assert drawing_for("state one") is None


def test_a_state_whose_drawing_is_there_answers_with_its_path(tmp_path, monkeypatch):
    monkeypatch.setattr("origenerator.action_drawings.DRAWINGS_DIR", tmp_path)
    drawn = tmp_path / "state-one.png"
    drawn.write_bytes(b"not really a drawing, but a file")

    assert drawing_for("state one") == drawn


def test_a_drawing_the_running_copy_carries_answers_before_the_librarys(
        tmp_path, monkeypatch):
    """A preview runs out of its own folder on the library's own images, so a
    drawing it carries for an action it has renamed is what its buttons wear --
    and the production app goes on reading the library's."""
    monkeypatch.setattr("origenerator.action_drawings.DRAWINGS_DIR", tmp_path / "library")
    monkeypatch.setattr("origenerator.action_drawings.OWN_DRAWINGS_DIR", tmp_path / "own")
    for folder in ("library", "own"):
        (tmp_path / folder).mkdir()
        (tmp_path / folder / "state-one.png").write_bytes(b"a file, not a drawing")

    assert drawing_for("state one") == tmp_path / "own" / "state-one.png"


def test_the_drawings_stay_in_the_folders_every_copy_of_the_app_reads():
    assert drawing_path("state one").parent.name == "picture_states"
    assert OWN_DRAWINGS_DIR.name == "picture_states"

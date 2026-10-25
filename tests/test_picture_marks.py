"""Fixture values are fabricated throughout (see CLAUDE.md)."""
from __future__ import annotations

from origenerator.picture_marks import MARKS_DIR, mark_for, mark_path


def test_a_states_drawing_sits_under_the_librarys_own_folder_named_for_it():
    assert mark_path("state one") == MARKS_DIR / "state-one.png"
    # The shapes the real names come in: two states in one, and a hyphen.
    assert mark_path("Alpha, Beta") == MARKS_DIR / "alpha-beta.png"
    assert mark_path("no-hands gamma") == MARKS_DIR / "no-hands-gamma.png"


def test_a_state_with_no_drawing_installed_answers_with_none(tmp_path, monkeypatch):
    monkeypatch.setattr("origenerator.picture_marks.MARKS_DIR", tmp_path)

    assert mark_for("state one") is None


def test_a_state_whose_drawing_is_there_answers_with_its_path(tmp_path, monkeypatch):
    monkeypatch.setattr("origenerator.picture_marks.MARKS_DIR", tmp_path)
    drawn = tmp_path / "state-one.png"
    drawn.write_bytes(b"not really a picture, but a file")

    assert mark_for("state one") == drawn


def test_a_drawing_the_running_copy_carries_answers_before_the_librarys(
        tmp_path, monkeypatch):
    """A preview runs out of its own folder on the library's own pictures, so a
    drawing it carries for an action it has renamed is what its buttons wear --
    and the production app goes on reading the library's."""
    monkeypatch.setattr("origenerator.picture_marks.MARKS_DIR", tmp_path / "library")
    monkeypatch.setattr("origenerator.picture_marks.OWN_MARKS_DIR", tmp_path / "own")
    for folder in ("library", "own"):
        (tmp_path / folder).mkdir()
        (tmp_path / folder / "state-one.png").write_bytes(b"a file, not a picture")

    assert mark_for("state one") == tmp_path / "own" / "state-one.png"

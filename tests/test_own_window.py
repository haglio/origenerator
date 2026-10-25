"""Opening each of the two windows this app has no button for.

Everything else about them is tested a piece at a time -- the line of images,
the walk, the two windows themselves -- and none of that runs the launch. The
launcher's own test asks what the script starts, and the smoke test imports what
the app names; between them sits the thing a user actually meets, which is
``main()`` running to a window on screen. It broke there: ``dress_application``
gained an argument on main and both of these went on calling it with one, so the
double-click wrote a TypeError into state and opened nothing.
"""
from __future__ import annotations

import pytest
from PyQt6.QtWidgets import (
    QApplication,
    QLabel,
    QMessageBox,
    QPlainTextEdit,
)
from shared_ui.preview import Preview

from origenerator import (
    act_settings,
    animation_settings,
    branch_session,
    check_animations,
    config,
    own_window,
    sort_images,
)
from origenerator.gui import stylesheet
from origenerator.gui.animation_check_window import (
    HEADING,
    POSITIVE,
    AnimationCheckWindow,
)


@pytest.fixture
def said(monkeypatch):
    spoken: list[str] = []
    monkeypatch.setattr(QMessageBox, "information",
                        lambda parent, title, text: spoken.append(text))
    monkeypatch.setattr(QMessageBox, "critical",
                        lambda parent, title, text: spoken.append(text))
    return spoken


@pytest.fixture
def a_library_of_its_own(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "gallery.db")
    monkeypatch.setattr(animation_settings, "SETTINGS_PATH",
                        tmp_path / "animation_settings.json")
    return tmp_path


def test_sorting_says_so_when_every_image_already_has_an_action(
        qapp, a_library_of_its_own, said):
    assert sort_images.main() == 0

    assert said == ["Every image already says what it shows."]


def test_checking_animations_opens_on_the_first_of_them(
        a_library_of_its_own, monkeypatch):
    up: list[AnimationCheckWindow] = []

    def what_is_up(app) -> int:
        up.extend(w for w in app.topLevelWidgets()
                  if isinstance(w, AnimationCheckWindow))
        return 0

    monkeypatch.setattr(QApplication, "exec", what_is_up)

    assert check_animations.main() == 0

    assert len(up) == 1
    assert up[0].isVisible()
    assert up[0].findChild(QLabel, HEADING).text()


def test_an_animation_with_no_sample_starts_from_the_acts_own_settings(
        a_library_of_its_own, monkeypatch):
    """His ask: the per-act settings are the starting position where nothing
    kept was ever made this way."""
    monkeypatch.setattr(act_settings, "pinned_settings",
                        lambda act, lane: {"workflow": "wan22_i2v",
                                           "params": {"positive_prompt": "the act's own"}})

    made = check_animations.the_animation_window()

    assert made.findChild(QPlainTextEdit, POSITIVE).toPlainText() == "the act's own"


def test_each_window_names_itself_to_windows_under_the_apps_own_name():
    """A window that claims nothing is grouped on the taskbar with the python
    that launched it, and wears that icon; one that claims the app's own name
    would answer the pinned Origenerator button in the app's place."""
    assert own_window.taskbar_identity(
        "Sorting images", None) == "Origenerator.SortingImages"
    assert own_window.taskbar_identity(
        "Checking animations", None) == "Origenerator.CheckingAnimations"


def test_a_window_out_of_a_branch_is_shown_as_a_preview():
    """Amber instead of magenta, and a taskbar group of its own, the way every
    preview in the family shows -- the production app's windows keep both."""
    preview = Preview(feature="a branch")

    assert own_window.taskbar_identity("Sorting images", preview).endswith(
        ".Preview")


def test_a_window_out_of_a_branch_wears_the_preview_ink(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "STATE_DIR", tmp_path)

    told = own_window.taskbar_app("Sorting images", "sort_images.vbs",
                                  Preview(feature="a branch"))

    assert told.icon == tmp_path / "preview_icon.ico"
    assert told.icon.is_file()


def test_the_production_apps_own_windows_wear_its_own_icon():
    told = own_window.taskbar_app("Sorting images", "sort_images.vbs", None)

    assert told.icon.name == "icon.ico"


def test_what_the_window_is_dressed_as_is_what_this_copy_is(
        a_library_of_its_own, said, monkeypatch):
    """The app answers this question for its own window with ``shown_as``; these
    two asked nobody and came up in the production app's colors."""
    dressed = []
    monkeypatch.setattr(branch_session, "shown_as",
                        lambda checkout: Preview(feature="a branch"))
    monkeypatch.setattr(stylesheet, "dress_application",
                        lambda app, preview: dressed.append(preview))

    assert sort_images.main() == 0

    assert dressed == [Preview(feature="a branch")]


def test_opening_the_sorting_window_claims_that_name(
        a_library_of_its_own, said, monkeypatch):
    claimed = []
    monkeypatch.setattr(own_window, "_claim_the_taskbar", claimed.append)

    assert sort_images.main() == 0

    assert claimed == ["Origenerator.SortingImages"]


def test_the_taskbar_is_told_the_apps_icon_and_how_to_reopen_the_window():
    """Told neither, the button wears the icon of the python that started the
    window whenever the window is too busy to answer for itself."""
    told = own_window.taskbar_app("Sorting images", "sort_images.vbs", None)

    assert told.name == "Origenerator — Sorting images"
    assert told.icon.name == "icon.ico"
    assert told.relaunch.endswith('sort_images.vbs"')


def test_opening_the_sorting_window_dresses_its_taskbar_button(
        a_library_of_its_own, said, monkeypatch):
    dressed = []
    monkeypatch.setattr(
        own_window, "_dress_the_taskbar_button",
        lambda app, title, launcher, preview: dressed.append((title, launcher)))

    assert sort_images.main() == 0

    assert dressed == [("Sorting images", "sort_images.vbs")]

from __future__ import annotations

from pathlib import Path

import pytest
from PySide6.QtCore import QObject

from origenerator.fixes_being_chosen import Shown
from origenerator.gui.choosing_fixes import (
    LONGEST_WAIT_FOR_THE_POINTER_MS,
    RESTS_AFTER_MS,
    ChoosingFixes,
)


class FakeFixesBeingChosen:
    def __init__(self):
        self.refuses = self.still_writing = False
        self.asked: list = []

    def change(self, row, filename, part, what, to):
        self.asked.append(("change", row["prompt_id"], filename, part, what, to))
        return None if self.refuses else Shown({"filename": filename}, None, Path(filename))

    def any_being_written(self) -> bool:
        return self.still_writing

    def record(self) -> list:
        self.asked.append("record")
        return ["g0"]

    def settle(self) -> list:
        self.asked.append("settle")
        return ["g0"]


class Told:
    def __init__(self):
        self.told: list = []
        self.pointer_on_the_fixes = False

    def pointer_is_on_the_fixes(self) -> bool:
        return self.pointer_on_the_fixes

    def get_generation(self, prompt_id):
        return {"prompt_id": prompt_id} if prompt_id == "g0" else None

    def show_fixes_changed(self, prompt_id, filename, shown) -> None:
        self.told.append(("tab", prompt_id, filename, shown is not None))

    def take_fixes_recorded(self, row) -> None:
        self.told.append(("tab takes the record", row["prompt_id"]))

    def note_versions_deleted(self, row) -> None:
        self.told.append(("slideshows", row["prompt_id"]))

    def read_the_gallery_again(self) -> None:
        self.told.append("gallery read again")


@pytest.fixture
def choosing(qapp):
    fixes, told, owner = FakeFixesBeingChosen(), Told(), QObject()
    made = ChoosingFixes(fixes, db=told, tabs=told, slideshows=told,
                         read_the_gallery_again=told.read_the_gallery_again, parent=owner)
    yield made, fixes, told.told
    made.rest.stop()


@pytest.fixture
def pointing_at_the_fixes(qapp):
    fixes, told, owner = FakeFixesBeingChosen(), Told(), QObject()
    told.pointer_on_the_fixes = True
    made = ChoosingFixes(fixes, db=told, tabs=told, slideshows=told,
                         read_the_gallery_again=told.read_the_gallery_again, parent=owner)
    yield made, fixes, told
    made.rest.stop()


def test_a_change_made_to_a_fix_shows_on_the_tabs_at_once_and_the_gallery_waits_for_a_rest(
        choosing):
    made, fixes, told = choosing

    made.change("g0", "enhanced.png", "faces", "on", False)

    assert fixes.asked == [("change", "g0", "enhanced.png", "faces", "on", False)]
    assert told == [("tab", "g0", "enhanced.png", True)], (
        "reading the whole gallery again after each click is what the image waited seconds on")
    assert made.rest.isActive()


def test_once_the_choosing_rests_the_fixes_are_recorded_and_the_gallery_is_read_again_once(
        choosing):
    made, fixes, told = choosing

    made.rest.timeout.emit()

    assert fixes.asked == ["record"]
    assert told == ["gallery read again", ("tab takes the record", "g0"), ("slideshows", "g0")]


def test_the_record_waits_again_while_the_image_is_still_being_written(choosing):
    made, fixes, told = choosing
    fixes.still_writing = True

    made.rest.timeout.emit()

    assert (fixes.asked, told) == ([], [])
    assert made.rest.isActive()


def test_the_record_waits_while_the_pointer_is_still_on_the_fixes(pointing_at_the_fixes):
    made, fixes, told = pointing_at_the_fixes

    made.rest.timeout.emit()

    assert (fixes.asked, told.told) == ([], []), (
        "reading the gallery again freezes the window for about a second, and a click on a fix "
        "two seconds after the last one waited on it")
    assert made.rest.isActive()
    told.pointer_on_the_fixes = False
    made.rest.timeout.emit()
    assert fixes.asked == ["record"]


def test_a_pointer_left_on_the_fixes_does_not_hold_the_record_back_for_good(
        pointing_at_the_fixes):
    made, fixes, _told = pointing_at_the_fixes
    longest = LONGEST_WAIT_FOR_THE_POINTER_MS // RESTS_AFTER_MS

    for _rest in range(longest):
        made.rest.timeout.emit()
    assert fixes.asked == []
    made.rest.timeout.emit()

    assert fixes.asked == ["record"]


def test_a_new_change_starts_the_wait_for_the_pointer_over(pointing_at_the_fixes):
    made, fixes, _told = pointing_at_the_fixes
    for _rest in range(LONGEST_WAIT_FOR_THE_POINTER_MS // RESTS_AFTER_MS):
        made.rest.timeout.emit()

    made.change("g0", "enhanced.png", "faces", "on", False)
    made.rest.timeout.emit()

    assert fixes.asked == [("change", "g0", "enhanced.png", "faces", "on", False)]


def test_a_change_that_is_refused_puts_the_tabs_back_and_starts_no_wait(choosing):
    made, fixes, told = choosing
    fixes.refuses = True

    made.change("g0", "enhanced.png", "faces", "on", False)

    assert told == [("tab", "g0", "enhanced.png", False)]
    assert not made.rest.isActive()


def test_a_change_to_an_item_no_longer_in_the_gallery_asks_nothing_of_the_fixes(choosing):
    made, fixes, told = choosing

    made.change("gone", "enhanced.png", "faces", "on", False)

    assert (fixes.asked, told) == ([], [("tab", "gone", "enhanced.png", False)])


def test_what_reads_the_record_can_have_the_fixes_just_chosen_recorded_first(choosing):
    made, fixes, told = choosing
    made.rest.start()
    enhance_again = made.settled_before(
        lambda prompt_id, filename: fixes.asked.append(("enhance again", prompt_id, filename)))

    enhance_again("g0", "enhanced.png")

    assert fixes.asked == ["settle", ("enhance again", "g0", "enhanced.png")], (
        "a Re-enhance pressed straight after a click would leave out what the record said, "
        "never what the screen showed")
    assert told[0] == "gallery read again"
    assert not made.rest.isActive()


def test_closing_records_the_fixes_chosen_and_shows_nothing(choosing):
    made, fixes, told = choosing
    made.rest.start()

    made.close()

    assert (fixes.asked, told) == (["settle"], [])
    assert not made.rest.isActive()

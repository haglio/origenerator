"""What a show is handed when it opens.

SlideshowView took nineteen constructor arguments, six of them callbacks back
into the gallery and three of them the players' HUD's description of the set.
Neither group ever travelled alone — the six are passed at exactly one place,
always all six, and the three go together at every caller that passes any of
them — so each is one argument now. These pin the two records and the fact that
the show still reads its wiring off them.
"""

from dataclasses import FrozenInstanceError
from unittest.mock import MagicMock

import pytest
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QKeyEvent

from origenerator.gui.show_wiring import HudFacts, ShowActions
from origenerator.gui.slideshow_view import SlideshowView

_ITEMS = [("a.png", "image", "id-a", None), ("b.png", "image", "id-b", None)]


def _press(view, key, modifier=Qt.KeyboardModifier.NoModifier):
    view.keyPressEvent(QKeyEvent(QKeyEvent.Type.KeyPress, key, modifier))


@pytest.fixture
def wired(qtbot):
    """A show with every one of the six acts recorded rather than performed."""
    calls: dict[str, list] = {name: [] for name in
                              ("delete", "enhance", "star", "lock", "reset",
                               "drive_toggle")}

    def record(name, result=None):
        def _act(*args):
            calls[name].append(args)
            return result
        return _act

    actions = ShowActions(
        delete=record("delete"),
        enhance=record("enhance", result=True),
        star=record("star"),
        lock=record("lock"),
        reset=record("reset"),
        drive_toggle=record("drive_toggle"),
    )
    view = SlideshowView(_ITEMS, player=MagicMock(), shuffle=lambda order: None,
                         actions=actions)
    qtbot.addWidget(view)
    return view, calls


def test_the_six_acts_travel_as_one_record_and_land_where_they_did(wired):
    view, calls = wired

    _press(view, Qt.Key.Key_Down)     # hold: stars, and asks for an enhancement
    assert calls["star"] == [("id-a",)]
    assert calls["enhance"] == [("id-a",)]
    assert calls["lock"] == [("id-a",)]

    _press(view, Qt.Key.Key_Up)       # cull
    assert calls["delete"] == [("id-a",)]

    view.stroke_reset()
    assert calls["reset"] == [(view,)]


def test_a_show_handed_no_acts_at_all_just_does_less(qtbot):
    # Every field defaults to nothing, which is what a show opened by a test or
    # standing alone gets: the presses still work, they just ask nobody.
    view = SlideshowView(_ITEMS, player=MagicMock(), shuffle=lambda order: None)
    qtbot.addWidget(view)

    _press(view, Qt.Key.Key_Down)

    assert view._playlist.locked is True   # the hold itself is the show's own


def test_the_hud_facts_travel_as_one_record(qtbot):
    view = SlideshowView(_ITEMS, player=MagicMock(), shuffle=lambda order: None,
                         hud=HudFacts(order_label="Latest", looping=False,
                                      starred_ids={"id-b"}))
    qtbot.addWidget(view)

    assert view.hud_order_label == "Latest"
    assert view.hud_looping is False
    assert view.hud_is_favorite is False   # id-a is on screen, id-b is the star
    view.step(1)
    assert view.hud_is_favorite is True


def test_the_hud_facts_default_to_a_shuffled_loop_of_nothing_starred(qtbot):
    view = SlideshowView(_ITEMS, player=MagicMock(), shuffle=lambda order: None)
    qtbot.addWidget(view)

    assert (view.hud_order_label, view.hud_looping) == ("Shuffle", True)
    assert view.hud_is_favorite is False


def test_retuning_a_show_dresses_it_as_a_base_state(qtbot):
    # A hosted reset points the show at the region's base set, which is one KIND
    # of set and always the same one: shuffled, and not a loop anyone asked for.
    # Its two callers used to spell that out and could have disagreed; there is
    # one answer now, and the stars it already had are not part of it.
    view = SlideshowView(_ITEMS, player=MagicMock(), shuffle=lambda order: None,
                         hud=HudFacts(order_label="Latest", looping=True,
                                      starred_ids={"id-c"}))
    qtbot.addWidget(view)

    view.retune([("c.png", "image", "id-c", None)])

    assert (view.hud_order_label, view.hud_looping) == ("Shuffle", False)
    assert view.hud_is_favorite is True   # the stars survive a reset


def test_neither_record_can_be_edited_after_it_is_handed_over(qtbot):
    # They describe how a show was opened. A caller that wants a different
    # answer opens a different show, or retunes this one.
    with pytest.raises(FrozenInstanceError):
        ShowActions().delete = print
    with pytest.raises(FrozenInstanceError):
        HudFacts().looping = False

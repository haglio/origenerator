from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest
from funestra.testing import FakeEngine
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QKeyEvent

from origenerator.gui.slideshow_view import SlideshowView, ViewShow, ViewWiring
from origenerator.gui.slideshow_wiring import HudFacts, SlideshowActions

_ITEMS = [("a.png", "image", "id-a", None), ("b.png", "image", "id-b", None)]


def _press(view, key, modifier=Qt.KeyboardModifier.NoModifier):
    view.keyPressEvent(QKeyEvent(QKeyEvent.Type.KeyPress, key, modifier))


@pytest.fixture
def wired(qtbot):
    calls: dict[str, list] = {name: [] for name in
                              ("delete", "enhance", "star", "lock", "reset",
                               "drive_toggle")}

    def record(name, result=None):
        def _act(*args):
            calls[name].append(args)
            return result
        return _act

    actions = SlideshowActions(
        delete=record("delete"),
        enhance=record("enhance", result=True),
        favorite=record("star"),
        lock=record("lock"),
        reset=record("reset"),
        drive_toggle=record("drive_toggle"),
    )
    view = SlideshowView(_ITEMS, ViewShow(shuffle=lambda order: None,
                         actions=actions), ViewWiring(engine=FakeEngine()))
    qtbot.addWidget(view)
    return view, calls


def test_the_six_acts_travel_as_one_record_and_land_where_they_did(wired):
    view, calls = wired

    _press(view, Qt.Key.Key_Down)
    assert calls["star"] == [("id-a",)]
    assert calls["enhance"] == [("id-a",)]
    assert calls["lock"] == [("id-a",)]

    _press(view, Qt.Key.Key_Up)
    assert calls["delete"] == [("id-a",)]

    view.slideshow.slideshow_reset()
    assert calls["reset"] == [(view.slideshow,)]


def test_a_slideshow_handed_no_acts_at_all_just_does_less(qtbot):
    view = SlideshowView(_ITEMS, ViewShow(shuffle=lambda order: None), ViewWiring(engine=FakeEngine()))
    qtbot.addWidget(view)

    _press(view, Qt.Key.Key_Down)

    assert view.slideshow.locked is True


def test_the_hud_facts_travel_as_one_record(qtbot):
    view = SlideshowView(_ITEMS, ViewShow(shuffle=lambda order: None,
                         hud=HudFacts(order_label="Latest", favorite_ids={"id-b"})), ViewWiring(engine=FakeEngine()))
    qtbot.addWidget(view)

    assert view.slideshow.hud_order_label == "Latest"
    assert view.slideshow.hud_is_favorite is False
    view.slideshow.slideshow_step(1)
    view.slideshow.tick()
    assert view.slideshow.hud_is_favorite is True


def test_the_hud_facts_default_to_a_shuffled_set_of_nothing_favorite(qtbot):
    view = SlideshowView(_ITEMS, ViewShow(shuffle=lambda order: None), ViewWiring(engine=FakeEngine()))
    qtbot.addWidget(view)

    as_it_opens = (view.slideshow.hud_order_label, view.slideshow.hud_map().loop,
                   view.slideshow.hud_is_favorite)
    assert as_it_opens == ("Shuffle", "", False), (
        "the defaults are a shuffled set with nothing favorited: a slideshow asked for by the "
        "Gallery pane buttons, which is the ordinary case")


def test_retuning_a_slideshow_dresses_it_as_a_base_state(qtbot):
    view = SlideshowView(_ITEMS, ViewShow(shuffle=lambda order: None,
                         hud=HudFacts(order_label="Latest", favorite_ids={"id-c"})), ViewWiring(engine=FakeEngine()))
    qtbot.addWidget(view)

    view.slideshow.retune([("c.png", "image", "id-c", None)])

    assert view.slideshow.hud_order_label == "Shuffle"
    assert view.slideshow.hud_is_favorite is True


def test_neither_record_can_be_edited_after_it_is_handed_over(qtbot):
    with pytest.raises(FrozenInstanceError):
        SlideshowActions().delete = print
    with pytest.raises(FrozenInstanceError):
        HudFacts().order_label = "Latest"

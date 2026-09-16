"""The set a show plays, apart from whatever is putting its slides on screen.

What the two surfaces share is here; that a window redraws and a player is
handed a new playlist is theirs.  So what this covers is the seam between them:
when a fresh pass is dealt, and whether the slide that was on screen survived
into it.
"""
from __future__ import annotations

from origenerator.gui.show_set import ShowSet
from origenerator.gui.show_wiring import HudFacts
from origenerator.slideshow import in_order

_ITEMS = [("one.png", "image", "id-1"), ("two.png", "image", "id-2"),
          ("three.png", "image", "id-3")]


def _set(items=_ITEMS, **fields):
    dealt = []
    show_set = ShowSet(items, image_dwell_ms=4000, shuffle=in_order,
                       on_pass_change=dealt.append, **fields)
    return show_set, dealt


def test_narrowing_says_the_slide_on_screen_survived_into_the_new_pass():
    """A switch is a narrowing of what you are looking through, not a new show:
    the picture stays where it is kept, so the surface only has to say where in
    the set it now sits."""
    show_set, dealt = _set(hud=HudFacts(starred_ids={"id-2", "id-3"}))
    show_set.playlist.jump_to(1)          # standing on the favorite

    assert show_set.set_modes(f_mode=True, enhanced=False) is True
    assert dealt == [True]
    assert show_set.current_prompt_id() == "id-2"


def test_narrowing_past_the_slide_on_screen_stands_another_pass_up():
    """Kept out by the switch, it is gone from the pass — so the surface has to
    show whatever the new pass opens on rather than leave the old picture up."""
    show_set, dealt = _set(hud=HudFacts(starred_ids={"id-3"}))

    assert show_set.set_modes(f_mode=True, enhanced=False) is True
    assert dealt == [False]
    assert show_set.current_prompt_id() == "id-3"


def test_a_switch_that_would_leave_nothing_is_refused():
    """An empty show is not a mode — the button staying dark is the answer, and
    nothing is re-dealt."""
    show_set, dealt = _set()

    assert show_set.set_modes(f_mode=True, enhanced=False) is False
    assert dealt == []
    assert len(show_set.playlist) == 3


def test_a_reset_widens_only_where_something_was_narrowed():
    """With neither switch on there is nothing to widen back to, so the pass is
    left exactly as it is for the surface to start over in."""
    show_set, dealt = _set(hud=HudFacts(starred_ids={"id-1"}))

    assert show_set.drop_the_switches() is False
    assert dealt == []

    show_set.set_modes(f_mode=True, enhanced=False)
    dealt.clear()

    assert show_set.drop_the_switches() is True
    # A reset starts the set over rather than keeping the picture: the surface
    # shows whatever the fresh pass opens on.
    assert dealt == [False]
    assert len(show_set.playlist) == 3


def test_the_whole_set_keeps_what_a_switch_left_out():
    """An arrival while a switch is on is still there when it comes off, and
    one taken away is still gone — the set is kept by id beside the pass."""
    show_set, _dealt = _set(hud=HudFacts(starred_ids={"id-1"}))
    show_set.set_modes(f_mode=True, enhanced=False)

    show_set.forget_id("id-2")
    show_set.drop_the_switches()

    assert [item.prompt_id for item in show_set.playlist.items] == ["id-1", "id-3"]

"""The set a show plays, apart from whatever is putting its slides on screen.

What the two surfaces share is here; that a window redraws and a player is
handed a new playlist is theirs.  So what this covers is the seam between them:
when a fresh pass is dealt, and whether the slide that was on screen survived
into it.
"""
from __future__ import annotations

import random

import pytest
from player_core.hud_status import LATEST_LABEL, SHUFFLE_LABEL

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
    show_set, dealt = _set(hud=HudFacts(favorite_ids={"id-2", "id-3"}))
    show_set.playlist.jump_to(1)          # standing on the favorite

    assert show_set.set_modes(favorites_filter=True, enhanced=False) is True
    assert dealt == [True]
    assert show_set.current_prompt_id() == "id-2"


def test_narrowing_past_the_slide_on_screen_stands_another_pass_up():
    """Kept out by the switch, it is gone from the pass — so the surface has to
    show whatever the new pass opens on rather than leave the old picture up."""
    show_set, dealt = _set(hud=HudFacts(favorite_ids={"id-3"}))

    assert show_set.set_modes(favorites_filter=True, enhanced=False) is True
    assert dealt == [False]
    assert show_set.current_prompt_id() == "id-3"


def test_a_switch_that_would_leave_nothing_is_refused():
    """An empty show is not a mode — the button staying dark is the answer, and
    nothing is re-dealt."""
    show_set, dealt = _set()

    assert show_set.set_modes(favorites_filter=True, enhanced=False) is False
    assert dealt == []
    assert len(show_set.playlist) == 3


def test_a_reset_widens_only_where_something_was_narrowed():
    """With neither switch on there is nothing to widen back to, so the pass is
    left exactly as it is for the surface to start over in."""
    show_set, dealt = _set(hud=HudFacts(favorite_ids={"id-1"}))

    assert show_set.drop_the_switches() is False
    assert dealt == []

    show_set.set_modes(favorites_filter=True, enhanced=False)
    dealt.clear()

    assert show_set.drop_the_switches() is True
    # A reset starts the set over rather than keeping the picture: the surface
    # shows whatever the fresh pass opens on.
    assert dealt == [False]
    assert len(show_set.playlist) == 3


def test_the_whole_set_keeps_what_a_switch_left_out():
    """An arrival while a switch is on is still there when it comes off, and
    one taken away is still gone — the set is kept by id beside the pass."""
    show_set, _dealt = _set(hud=HudFacts(favorite_ids={"id-1"}))
    show_set.set_modes(favorites_filter=True, enhanced=False)

    show_set.forget_id("id-2")
    show_set.drop_the_switches()

    assert [item.prompt_id for item in show_set.playlist.items] == ["id-1", "id-3"]


def _pass(show_set) -> list[str]:
    playlist = show_set.playlist
    return [playlist.items[index].prompt_id for index in playlist.order]


def test_latest_plays_the_new_set_as_listed_from_the_top_still_narrowed():
    show_set, dealt = _set(hud=HudFacts(favorite_ids={"id-1", "id-5"}))
    show_set.set_modes(favorites_filter=True, enhanced=False)
    dealt.clear()
    newest_first = [("five.png", "image", "id-5"), ("four.png", "image", "id-4"),
                    ("one.png", "image", "id-1")]

    show_set.reorder(newest_first, latest=True)

    assert dealt == [False]
    assert _pass(show_set) == ["id-5", "id-1"]
    assert show_set.playlist.index == 0
    assert show_set.favorites_filter is True
    assert show_set.order_label == LATEST_LABEL


_TWELVE = [(f"{n}.png", "image", f"id-{n}") for n in range(12)]


@pytest.fixture
def seeded():
    state = random.getstate()
    random.seed(7)
    yield
    random.setstate(state)


def test_shuffle_plays_the_new_set_in_a_random_order(seeded):
    show_set, _dealt = _set()

    show_set.reorder(_TWELVE, latest=False)

    listed = [item[2] for item in _TWELVE]
    assert sorted(_pass(show_set)) == sorted(listed)
    assert _pass(show_set) != listed
    assert show_set.order_label == SHUFFLE_LABEL


def test_a_new_set_the_switches_would_empty_plays_whole_with_them_off():
    show_set, _dealt = _set(hud=HudFacts(favorite_ids={"id-1"}))
    show_set.set_modes(favorites_filter=True, enhanced=False)

    show_set.reorder([("nine.png", "image", "id-9")], latest=True)

    assert show_set.favorites_filter is False
    assert _pass(show_set) == ["id-9"]


def test_a_reset_after_latest_deals_a_shuffled_pass_with_the_switches_off(seeded):
    show_set, _dealt = _set(hud=HudFacts(favorite_ids={"id-1", "id-2"}))
    show_set.reorder(_TWELVE, latest=True)
    show_set.set_modes(favorites_filter=True, enhanced=False)

    show_set.retune(_TWELVE)

    assert show_set.favorites_filter is False
    assert sorted(_pass(show_set)) == sorted(item[2] for item in _TWELVE)
    assert _pass(show_set) != [item[2] for item in _TWELVE]
    assert show_set.order_label == SHUFFLE_LABEL


# --- the map around the slide on screen, and the loops along it -------------

from origenerator.gui.show_map import MapNeighbors, MapRow  # noqa: E402
from origenerator.slideshow import Slide  # noqa: E402

_SEEDS = {"id-1": (Slide("one-b.png", "image", "id-1b"), Slide("one-c.png", "image", "id-1c"))}
_ACTIONS = {"id-1": (Slide("one-x.png", "image", "id-1x"),),
            "id-1b": (Slide("one-bx.png", "image", "id-1bx"),)}


def _neighbors(prompt_id):
    actions = _ACTIONS.get(prompt_id, ())
    return MapNeighbors(seeds=_SEEDS.get(prompt_id, ()),
                        column=tuple(MapRow(slide, "dawn") for slide in actions),
                        label="fox", group=actions)


def _mapped(**fields):
    return _set(neighbors=_neighbors, **fields)


def _ids(slides) -> list:
    return [slide.prompt_id for slide in slides]


def test_the_map_is_the_slide_on_screen_with_its_seeds_right_and_its_configs_down():
    """A gamma: the item in the corner, the same configuration under other
    seeds running right, the same seed under other configurations running
    down — and nothing lit but the corner, since nothing is looping."""
    show_set, _dealt = _mapped()

    shown = show_set.map()

    assert shown.corner.prompt_id == "id-1"
    assert _ids(shown.seeds) == ["id-1b", "id-1c"]
    assert _ids(shown.actions) == ["id-1x"]
    assert (shown.playing, shown.loop) == (("corner", 0), "")
    assert (shown.label, tuple(row.label for row in shown.column)) == ("fox", ("dawn",))


def test_the_map_re_homes_on_whatever_comes_up():
    show_set, _dealt = _mapped()

    show_set.playlist.advance()

    shown = show_set.map()
    assert shown.corner.prompt_id == "id-2"
    assert (shown.seeds, shown.actions, shown.playing) == ((), (), ("corner", 0))


def test_looping_the_seeds_plays_the_row_round_under_a_map_that_holds_still():
    """The row becomes the pass, in the row's own order and starting on the
    slide on screen; as it plays the lit cell walks the row while the corner
    stays put — and the column is the lit seed's own, since every seed has
    other configurations of its own."""
    show_set, dealt = _mapped()

    assert show_set.start_loop("seed") is True
    assert dealt == [True]                       # the slide on screen stayed
    assert _ids(show_set.playlist.items) == ["id-1", "id-1b", "id-1c"]

    show_set.playlist.advance()
    shown = show_set.map()
    assert shown.corner.prompt_id == "id-1"      # the loop's anchor, not the slide
    assert _ids(shown.seeds) == ["id-1b", "id-1c"]
    assert shown.playing == ("seed", 0)
    assert shown.loop == "seed"
    assert _ids(shown.actions) == ["id-1bx"]      # the lit seed's column


def test_ending_the_loop_goes_back_to_browsing_with_the_slide_kept():
    """The browse resumes underneath; a slide the loop wandered onto that the
    set never held plays out first, and the browse is what comes next."""
    show_set, dealt = _mapped()
    show_set.start_loop("seed")
    show_set.playlist.advance()
    dealt.clear()

    assert show_set.end_loop() is True

    assert dealt == [True]
    assert _ids(show_set.playlist.items) == ["id-1b", "id-1", "id-2", "id-3"]
    assert show_set.current_prompt_id() == "id-1b"
    assert show_set.map().loop == ""
    assert show_set.end_loop() is False          # nothing left to end


def test_a_slide_taken_away_leaves_the_loop_it_was_in():
    """A running loop is drawn on the map from the pool it was dealt, not from
    the library — so a picture taken away has to leave that pool too, or the map
    goes on drawing it beside the ones still there."""
    show_set, _dealt = _mapped()
    show_set.start_loop("seed")

    show_set.forget_id("id-1b")

    assert [slide.prompt_id for slide in show_set.loop.pool] == ["id-1", "id-1c"]
    assert [cell.prompt_id for cell in show_set.map().seeds] == ["id-1c"]


def test_a_forward_step_in_a_loop_down_to_one_slide_leaves_the_loop():
    """A cull can leave a loop holding only the slide on screen, and stepping
    round a row of one is that same picture again — so the forward step ends the
    loop and lands on what the browse plays next, the way Right leaves a lock."""
    show_set, dealt = _mapped()
    show_set.start_loop("seed")
    show_set.playlist.drop("id-1b")
    show_set.playlist.drop("id-1c")
    dealt.clear()

    show_set.step(1)

    assert show_set.loop is None
    assert show_set.current_prompt_id() == "id-2"


def test_a_forward_step_in_a_loop_with_somewhere_to_go_stays_in_the_loop():
    """The row is what the forward step walks while it still holds another
    slide; only a row down to the one on screen is the dead end that ends it."""
    show_set, _dealt = _mapped()
    show_set.start_loop("seed")

    show_set.step(1)

    assert show_set.loop is not None
    assert show_set.current_prompt_id() == "id-1b"


def test_a_step_back_in_a_loop_down_to_one_slide_leaves_it_looping():
    """Only the forward step is the way out, as on a player: back is the loop's
    own step the other way, and what it finds in a row of one is that slide."""
    show_set, _dealt = _mapped()
    show_set.start_loop("seed")
    show_set.playlist.drop("id-1b")
    show_set.playlist.drop("id-1c")

    show_set.step(-1)

    assert show_set.loop is not None
    assert show_set.current_prompt_id() == "id-1"


def test_the_loop_key_steps_seeds_then_configs_then_off_and_round_again():
    show_set, _dealt = _mapped()

    assert show_set.step_loop() == "seed"
    assert show_set.step_loop() == "action"
    assert _ids(show_set.playlist.items) == ["id-1", "id-1x"]
    assert show_set.step_loop() == "off"
    assert show_set.step_loop() == "seed"


def test_a_loop_down_the_column_plays_the_whole_group_not_one_of_each_act():
    """The column steps between acts, so twins of one act share a row; the
    loop is the picture and every video of it, and its map is the loop."""
    twin = Slide("one-y.png", "image", "id-1y")
    whole = lambda pid: MapNeighbors(  # noqa: E731
        column=tuple(MapRow(slide, "dawn") for slide in _ACTIONS.get(pid, ())),
        group=(*_ACTIONS.get(pid, ()), twin) if pid == "id-1" else ())
    show_set, _dealt = _set(neighbors=whole)

    assert show_set.start_loop("action") is True

    assert _ids(show_set.playlist.items) == ["id-1", "id-1x", "id-1y"]
    assert _ids(show_set.map().actions) == ["id-1x", "id-1y"]


def test_an_axis_with_nothing_to_loop_is_stepped_over():
    seeds_only = lambda pid: MapNeighbors(seeds=_SEEDS.get(pid, ()))  # noqa: E731
    show_set, _dealt = _set(neighbors=seeds_only)

    assert show_set.step_loop() == "seed"
    assert show_set.step_loop() == "off"


def test_with_nothing_on_either_axis_the_loop_key_is_the_lock():
    show_set, dealt = _set()

    assert show_set.step_loop() == "lock"
    assert dealt == []


def test_more_seeds_widens_the_row_and_loops_what_it_becomes():
    beyond = (Slide("far.png", "image", "id-far"),)
    show_set, _dealt = _mapped(widen=lambda pid: beyond if pid == "id-1" else ())

    assert show_set.more_seeds() is True

    shown = show_set.map()
    assert _ids(shown.seeds) == ["id-1b", "id-1c", "id-far"]
    assert shown.loop == "seed"


def test_more_seeds_with_nothing_beyond_the_row_changes_nothing():
    show_set, dealt = _mapped(widen=lambda pid: ())

    assert show_set.more_seeds() is False
    assert dealt == [] and show_set.loop is None


def test_a_map_cell_the_pass_never_held_is_spliced_in_and_jumped_to():
    show_set, _dealt = _mapped()
    stranger = show_set.slide_for_path("one-x.png")

    assert stranger.prompt_id == "id-1x"
    assert show_set.jump_to(stranger) is True
    assert show_set.current_prompt_id() == "id-1x"
    assert _ids(show_set.playlist.items) == ["id-1", "id-2", "id-3", "id-1x"]
    assert show_set.map().corner.prompt_id == "id-1x"    # the map re-homed


def test_a_jump_off_a_loops_axis_ends_the_loop():
    show_set, _dealt = _mapped()
    show_set.start_loop("seed")

    show_set.jump_to(show_set.slide_for_path("one-x.png"))

    assert show_set.loop is None
    assert show_set.current_prompt_id() == "id-1x"


def test_navigation_walks_the_row_and_the_column_as_rings_headed_by_the_corner():
    show_set, _dealt = _mapped()

    assert show_set.nav_target("right").prompt_id == "id-1b"
    assert show_set.nav_target("left").prompt_id == "id-1c"
    assert show_set.nav_target("down").prompt_id == "id-1x"
    assert show_set.nav_target("up").prompt_id == "id-1x"

    show_set.playlist.advance()                  # id-2 has nothing around it
    assert show_set.nav_target("right") is None


def test_navigation_off_a_lit_seed_dives_into_that_seeds_own_column():
    show_set, _dealt = _mapped()
    show_set.start_loop("seed")
    show_set.playlist.advance()                  # the lit cell is id-1b

    assert show_set.nav_target("right").prompt_id == "id-1c"
    assert show_set.nav_target("left").prompt_id == "id-1"     # back to the corner
    assert show_set.nav_target("down").prompt_id == "id-1bx"


def test_a_switch_ends_a_loop_and_deals_the_browse():
    show_set, _dealt = _mapped(hud=HudFacts(favorite_ids={"id-2"}))
    show_set.start_loop("seed")

    show_set.set_modes(favorites_filter=True, enhanced=False)

    assert show_set.loop is None
    assert _ids(show_set.playlist.items) == ["id-2"]


def test_a_set_with_nothing_in_it_has_nothing_to_map_loop_widen_or_walk():
    show_set, dealt = _set(items=[], neighbors=_neighbors, widen=lambda pid: ())

    assert show_set.map() is None
    assert show_set.step_loop() == "lock"
    assert show_set.more_seeds() is False
    assert show_set.set_act_filter("fox") is False
    assert show_set.nav_target("right") is None
    assert dealt == []


def test_a_slide_that_joined_the_pass_mid_loop_is_mapped_as_itself():
    """A generation landing while a row loops is played in its turn, and the
    map re-homes on it rather than lighting a cell of a row it is not in."""
    show_set, _dealt = _mapped()
    show_set.start_loop("seed")
    show_set.playlist.add(Slide("new.png", "image", "id-new"))
    show_set.playlist.advance()

    shown = show_set.map()

    assert shown.corner.prompt_id == "id-new"
    assert (shown.playing, shown.loop) == (("corner", 0), "")


_ROW = [("one.png", "image", "id-1"), ("one-b.png", "image", "id-1b"),
        ("one-c.png", "image", "id-1c")]


def _row_mates(prompt_id):
    """Every slide of the one row is every other's seed, as a folder's pictures are."""
    in_the_row = any(item[2] == prompt_id for item in _ROW)
    return MapNeighbors(seeds=tuple(Slide.of(item) for item in _ROW
                                    if in_the_row and item[2] != prompt_id), label="fox")


def test_a_set_that_is_one_seed_row_opens_as_that_row_looping():
    """A folder played as a show is its seeds played round and round, which is
    all a seed loop is — so the map says so from the first slide."""
    show_set, dealt = _set(items=_ROW, neighbors=_row_mates)

    shown = show_set.map()

    assert (shown.loop, shown.playing) == ("seed", ("corner", 0))
    assert _ids(shown.seeds) == ["id-1b", "id-1c"]
    assert dealt == []                           # it was already playing the row


def test_a_row_opened_part_way_along_lights_its_cells_in_the_order_they_play():
    show_set, _dealt = _set(items=_ROW, neighbors=_row_mates, start=1)

    show_set.playlist.advance()
    shown = show_set.map()

    assert _ids((shown.corner, *shown.seeds)) == ["id-1b", "id-1c", "id-1"]
    assert shown.playing == ("seed", 0)


def test_a_set_with_a_slide_from_outside_the_row_opens_browsing():
    show_set, _dealt = _set(items=[*_ROW, ("two.png", "image", "id-2")], neighbors=_row_mates)

    assert show_set.map().loop == ""


def test_a_lone_slide_is_no_loop():
    show_set, _dealt = _set(items=_ROW[:1], neighbors=_row_mates)

    assert show_set.map().loop == ""


def test_the_loop_button_over_a_row_opened_looping_ends_the_loop():
    show_set, _dealt = _set(items=_ROW, neighbors=_row_mates)

    assert show_set.end_loop() is True
    assert show_set.map().loop == ""


def test_a_new_set_that_is_one_row_is_taken_up_looping_too():
    show_set, _dealt = _set(neighbors=_row_mates)
    assert show_set.map().loop == ""

    show_set.reseed(_ROW)

    assert show_set.map().loop == "seed"


def test_a_generation_landing_in_a_row_that_is_looping_joins_the_loop():
    show_set, _dealt = _set(items=_ROW[:2], neighbors=_row_mates)
    landed = Slide.of(_ROW[2])

    show_set.remember(landed)
    show_set.playlist.add(landed)
    show_set.playlist.advance()

    shown = show_set.map()
    assert _ids((shown.corner, *shown.seeds)) == ["id-1", "id-1b", "id-1c"]
    assert (shown.loop, shown.playing) == ("seed", ("seed", 1))


# --- the act filter: the map's row buttons, and the session's spoken acts ------

_NAMED_FOR = {"id-1": "Source image, alpha", "id-2": "beta", "id-3": "alpha"}


def _acts(prompt_ids):
    return {prompt_id: _NAMED_FOR.get(prompt_id, "") for prompt_id in prompt_ids}


def _filterable(**fields):
    return _set(acts=_acts, **fields)


def test_an_act_filter_narrows_the_pass_to_what_is_named_for_that_act():
    show_set, dealt = _filterable()

    assert show_set.set_act_filter("alpha") is True

    assert _ids(show_set.playlist.items) == ["id-1", "id-3"]
    assert show_set.act_filter == "alpha"
    assert dealt == [True]                      # the slide on screen shows that act


def test_a_filter_that_would_leave_nothing_is_refused_and_the_pass_left_alone():
    """A filter that selected nothing is a dead end, not a mode: the set plays
    on, and the row's button stays dark."""
    show_set, dealt = _filterable()

    assert show_set.set_act_filter("gamma") is False

    assert (show_set.act_filter, dealt, len(show_set.playlist)) == ("", [], 3)


def test_a_filter_naming_two_acts_keeps_only_what_is_named_for_both():
    """Set from a row carrying two acts it names both, and only a generation
    carrying both answers it — the rule the panel lights its rows by."""
    show_set, _dealt = _filterable()

    assert show_set.set_act_filter("source image, alpha") is True

    assert _ids(show_set.playlist.items) == ["id-1"]


def test_a_reset_drops_the_act_filter_with_the_other_switches():
    show_set, dealt = _filterable()
    show_set.set_act_filter("beta")
    dealt.clear()

    assert show_set.drop_the_switches() is True

    assert (show_set.act_filter, len(show_set.playlist), dealt) == ("", 3, [False])


def test_a_landing_is_asked_about_afresh_because_it_can_rename_what_was_there():
    """A video landing makes its picture a source, so what the library said
    before it landed is not what a filter may go on matching by."""
    named_for = dict(_NAMED_FOR)
    show_set, _dealt = _set(acts=lambda ids: {pid: named_for.get(pid, "") for pid in ids})
    show_set.set_act_filter("alpha")
    assert show_set.passes(Slide("two.png", "image", "id-2")) is False

    named_for["id-2"] = "Source image, alpha"
    show_set.remember(Slide("four.mp4", "video", "id-4"))

    assert show_set.passes(Slide("two.png", "image", "id-2")) is True


def test_a_configuration_rows_button_is_told_from_an_acts_by_the_row_itself():
    """Half the column is configurations and half is acts, and the two are
    pressed differently — so the map says which a row is rather than leaving it
    to be guessed from the words in its gutter."""
    a_configuration = Slide("one-x.png", "image", "id-1x")
    an_act = Slide("one-y.png", "image", "id-1y")
    both = lambda pid: MapNeighbors(  # noqa: E731
        column=(MapRow(a_configuration, "E629425B", configuration=True),
                MapRow(an_act, "alpha")) if pid == "id-1" else ())
    show_set, _dealt = _set(neighbors=both)

    assert show_set.configuration_row("e629425b") is a_configuration
    assert show_set.configuration_row("alpha") is None
    assert show_set.configuration_row("nobody") is None

"""The set a slideshow plays, apart from whatever is putting its slides on screen.

What the two surfaces share is here; that a window redraws and a Funestra is
handed a new playlist is theirs.  So what this covers is the seam between them:
when a fresh pass is dealt, and whether the slide that was on screen survived
into it.
"""
from __future__ import annotations

import random

import pytest
from funestra.hud_title import LATEST_LABEL, SHUFFLE_LABEL
from funestra.loop_cycle import ACTION, LOCK, OFF, SEED

from origenerator.gui.hud_nav_map import NavMapNeighbors, NavMapRow
from origenerator.gui.slideshow_set import SlideshowSet, item_note, narrow_to_the_act_on_screen
from origenerator.gui.slideshow_wiring import HudFacts, SlideshowActions
from origenerator.slideshow import LIVE, Slide, SlideshowFilters, in_order
from tests.slideshow_support import slides_named

_ITEMS = [("one.png", "image", "id-1"), ("two.png", "image", "id-2"),
          ("three.png", "image", "id-3")]


def _set(items=_ITEMS, *, hud=None, start=None, **asked_of_the_library):
    dealt = []
    slideshow_set = SlideshowSet(items,
                                 actions=SlideshowActions(**asked_of_the_library),
                                 shuffle=in_order, start=start, hud=hud,
                                 on_pass_change=dealt.append)
    return slideshow_set, dealt


def test_narrowing_says_the_slide_on_screen_survived_into_the_new_pass():
    """A switch is a narrowing of what you are looking through, not a new slideshow:
    the image stays where it is kept, so the surface only has to say where in
    the set it now sits."""
    slideshow_set, dealt = _set(hud=HudFacts(favorite_ids={"id-2", "id-3"}))
    slideshow_set.playlist.jump_to(1)          # standing on the favorite

    assert slideshow_set.set_filters(SlideshowFilters(favorites=True)) is True
    assert dealt == [True]
    assert slideshow_set.current_prompt_id() == "id-2"


def test_narrowing_past_the_slide_on_screen_stands_another_pass_up():
    """Kept out by the switch, it is gone from the pass — so the surface has to
    show whatever the new pass opens on rather than leave the old image up."""
    slideshow_set, dealt = _set(hud=HudFacts(favorite_ids={"id-3"}))

    assert slideshow_set.set_filters(SlideshowFilters(favorites=True)) is True
    assert dealt == [False]
    assert slideshow_set.current_prompt_id() == "id-3"


def test_a_filter_pressed_is_told_of_and_one_taken_up_is_not():
    told = []
    slideshow_set, _dealt = _set(hud=HudFacts(favorite_ids={"id-1"}), filters_changed=told.append)

    slideshow_set.take_up(SlideshowFilters(favorites=True))
    slideshow_set.set_filters(SlideshowFilters())

    assert told == [SlideshowFilters()]


def test_a_switch_that_would_leave_nothing_is_refused():
    """An empty slideshow is not a mode — the button staying dark is the answer, and
    nothing is re-dealt."""
    slideshow_set, dealt = _set()

    assert slideshow_set.set_filters(SlideshowFilters(favorites=True)) is False
    assert dealt == []
    assert len(slideshow_set.playlist) == 3


def test_a_reset_widens_only_where_something_was_narrowed():
    """With neither switch on there is nothing to widen back to, so the pass is
    left exactly as it is for the surface to start over in."""
    slideshow_set, dealt = _set(hud=HudFacts(favorite_ids={"id-1"}))

    assert slideshow_set.drop_the_filters() is False
    assert dealt == []

    slideshow_set.set_filters(SlideshowFilters(favorites=True))
    dealt.clear()

    assert slideshow_set.drop_the_filters() is True
    # A reset starts the set over rather than keeping the image: the surface
    # shows whatever the fresh pass opens on.
    assert dealt == [False]
    assert len(slideshow_set.playlist) == 3


def test_the_whole_set_keeps_what_a_switch_left_out():
    """An arrival while a switch is on is still there when it comes off, and
    one taken away is still gone — the set is kept by id beside the pass."""
    slideshow_set, _dealt = _set(hud=HudFacts(favorite_ids={"id-1"}))
    slideshow_set.set_filters(SlideshowFilters(favorites=True))

    slideshow_set.forget_id("id-2")
    slideshow_set.drop_the_filters()

    assert [item.prompt_id for item in slideshow_set.playlist.items] == ["id-1", "id-3"]


def _pass(slideshow_set) -> list[str]:
    playlist = slideshow_set.playlist
    return [playlist.items[index].prompt_id for index in playlist.order]


def test_latest_plays_the_new_set_as_listed_from_the_top_still_narrowed():
    slideshow_set, dealt = _set(hud=HudFacts(favorite_ids={"id-1", "id-5"}))
    slideshow_set.set_filters(SlideshowFilters(favorites=True))
    dealt.clear()
    newest_first = [("five.png", "image", "id-5"), ("four.png", "image", "id-4"),
                    ("one.png", "image", "id-1")]

    slideshow_set.reorder(newest_first, latest=True)

    assert dealt == [False]
    assert _pass(slideshow_set) == ["id-5", "id-1"]
    assert slideshow_set.playlist.index == 0
    assert slideshow_set.filters.favorites is True
    assert slideshow_set.order_label == LATEST_LABEL


_TWELVE = [(f"{n}.png", "image", f"id-{n}") for n in range(12)]


@pytest.fixture
def seeded():
    state = random.getstate()
    random.seed(7)
    yield
    random.setstate(state)


def test_shuffle_plays_the_new_set_in_a_random_order(seeded):
    slideshow_set, _dealt = _set()

    slideshow_set.reorder(_TWELVE, latest=False)

    listed = [item[2] for item in _TWELVE]
    assert sorted(_pass(slideshow_set)) == sorted(listed)
    assert _pass(slideshow_set) != listed
    assert slideshow_set.order_label == SHUFFLE_LABEL


def test_a_new_set_the_switches_would_empty_plays_whole_with_them_off():
    slideshow_set, _dealt = _set(hud=HudFacts(favorite_ids={"id-1"}))
    slideshow_set.set_filters(SlideshowFilters(favorites=True))

    slideshow_set.reorder([("nine.png", "image", "id-9")], latest=True)

    assert slideshow_set.filters.favorites is False
    assert _pass(slideshow_set) == ["id-9"]


def test_a_reset_after_latest_deals_a_shuffled_pass_with_the_switches_off(seeded):
    slideshow_set, _dealt = _set(hud=HudFacts(favorite_ids={"id-1", "id-2"}))
    slideshow_set.reorder(_TWELVE, latest=True)
    slideshow_set.set_filters(SlideshowFilters(favorites=True))

    slideshow_set.retune(_TWELVE)

    assert slideshow_set.filters.favorites is False
    assert sorted(_pass(slideshow_set)) == sorted(item[2] for item in _TWELVE)
    assert _pass(slideshow_set) != [item[2] for item in _TWELVE]
    assert slideshow_set.order_label == SHUFFLE_LABEL


def test_a_shuffled_pass_begun_on_a_slide_plays_every_other_one_before_coming_back(seeded):
    slideshow_set = SlideshowSet(_TWELVE, actions=SlideshowActions(),
                                 start=5)
    played = [slideshow_set.current_prompt_id()]
    for _ in _TWELVE[1:]:
        slideshow_set.playlist.advance()
        played.append(slideshow_set.current_prompt_id())

    assert played[0] == "id-5"
    assert sorted(played) == sorted(item[2] for item in _TWELVE)


# --- an image that something is being made of -------------------------------

def test_a_pass_dealt_while_an_image_of_it_is_being_enhanced_opens_on_it():
    slideshow_set, _dealt = _set(hud=HudFacts(enhancing={"id-3": "running"}))

    assert _pass(slideshow_set) == ["id-3", "id-1", "id-2"]
    assert slideshow_set.current_prompt_id() == "id-3"


def test_an_image_whose_enhancement_is_still_waiting_keeps_its_place():
    slideshow_set, _dealt = _set(hud=HudFacts(enhancing={"id-3": "queued"}))

    assert _pass(slideshow_set) == ["id-1", "id-2", "id-3"]


def test_a_pass_opened_on_a_named_slide_stays_on_it_whatever_is_being_made():
    slideshow_set, _dealt = _set(start=1, hud=HudFacts(enhancing={"id-3": "running"}))

    assert slideshow_set.current_prompt_id() == "id-2"


def test_a_new_set_opens_on_the_image_being_made_in_it():
    slideshow_set, _dealt = _set()
    slideshow_set.note_enhancing({"id-2": "running"})

    slideshow_set.reorder(_ITEMS, latest=True)

    assert slideshow_set.current_prompt_id() == "id-2"


def test_a_run_still_streaming_its_frames_leads_when_the_slideshow_is_asked_to():
    slideshow_set, _dealt = _set()
    slideshow_set.playlist.add(Slide(b"frame", LIVE, "id-run"))

    assert slideshow_set.lead_with_what_is_being_made() is True
    assert slideshow_set.current_prompt_id() == "id-run"


def test_an_image_being_made_holds_the_screen_half_as_long_as_the_pace():
    slideshow_set, _dealt = _set(hud=HudFacts(enhancing={"id-2": "queued", "id-3": "running"}))
    plain, waiting, being_made = (Slide.of(item) for item in _ITEMS)

    assert slideshow_set.pace_for(being_made, 5) == 2.5
    assert slideshow_set.pace_for(waiting, 5) == 5
    assert slideshow_set.pace_for(plain, 5) == 5


_TWO_VERSIONS = [("one_enhanced.png", "image", "Enhancement 1/1"), ("one.png", "image", "Original")]


def test_the_note_on_an_image_filed_once_with_nothing_in_flight_says_nothing():
    slideshow_set, _dealt = _set()

    assert item_note(slideshow_set, versions=[], version_index=0) == ""


def test_the_note_names_the_version_on_screen_by_its_name_alone():
    slideshow_set, _dealt = _set()

    assert item_note(slideshow_set, versions=_TWO_VERSIONS, version_index=0) == "Enhancement 1/1"
    assert item_note(slideshow_set, versions=_TWO_VERSIONS, version_index=1) == "Original"


def test_the_note_says_whether_a_better_version_is_being_made_or_waiting():
    slideshow_set, _dealt = _set()

    slideshow_set.note_enhancing({"id-1": "queued"})
    assert item_note(slideshow_set, versions=[], version_index=0) == "Enhancement queued"
    slideshow_set.note_enhancing({"id-1": "running"})
    assert item_note(slideshow_set, versions=[], version_index=0) == "Enhancing…"
    assert item_note(slideshow_set, versions=_TWO_VERSIONS, version_index=0) == (
        "Enhancement 1/1 · Enhancing…")


def test_an_enhancement_this_slideshow_asked_for_waits_until_the_gallery_says_otherwise():
    slideshow_set, _dealt = _set()

    slideshow_set.note_enhancement_asked("id-1")

    assert item_note(slideshow_set, versions=[], version_index=0) == "Enhancement queued"
    slideshow_set.note_enhancing({"id-1": "running"})
    assert item_note(slideshow_set, versions=[], version_index=0) == "Enhancing…"


def test_an_enhancement_that_landed_leaves_nothing_in_flight_to_say():
    slideshow_set, _dealt = _set()
    slideshow_set.note_enhancement_asked("id-1")
    slideshow_set.note_enhancing({"id-1": "running"})

    slideshow_set.note_enhancement_landed("id-1")

    assert item_note(slideshow_set, versions=[], version_index=0) == ""


def test_the_note_on_a_run_still_streaming_its_frames_says_it_is_being_generated():
    slideshow_set, _dealt = _set()
    slideshow_set.playlist.add(Slide(b"frame", LIVE, "id-run"))
    slideshow_set.lead_with_what_is_being_made()

    assert item_note(slideshow_set, versions=[], version_index=0) == "Generating…"


# --- the map around the slide on screen, and the loops along it -------------

_SEEDS = {"id-1": (Slide("one-b.png", "image", "id-1b"), Slide("one-c.png", "image", "id-1c"))}
_ACTIONS = {"id-1": (Slide("one-x.png", "image", "id-1x"),),
            "id-1b": (Slide("one-bx.png", "image", "id-1bx"),)}


def _neighbors(prompt_id):
    actions = _ACTIONS.get(prompt_id, ())
    return NavMapNeighbors(seeds=_SEEDS.get(prompt_id, ()),
                        column=tuple(NavMapRow(slide, "dawn") for slide in actions),
                        label="fox", group=actions)


def _mapped(**fields):
    return _set(neighbors=_neighbors, **fields)


def _ids(slides) -> list:
    return [slide.prompt_id for slide in slides]


def test_the_map_is_the_slide_on_screen_with_its_seeds_right_and_its_configs_down():
    """A gamma: the item in the corner, the same configuration under other
    seeds running right, the same seed under other configurations running
    down — and nothing lit but the corner, since nothing is looping."""
    slideshow_set, _dealt = _mapped()

    shown = slideshow_set.map()

    assert shown.corner.prompt_id == "id-1"
    assert _ids(shown.seeds) == ["id-1b", "id-1c"]
    assert _ids(shown.actions) == ["id-1x"]
    assert (shown.playing, shown.loop) == (("corner", 0), "")
    assert (shown.label, tuple(row.label for row in shown.column)) == ("fox", ("dawn",))


def test_the_map_re_homes_on_whatever_comes_up():
    slideshow_set, _dealt = _mapped()

    slideshow_set.playlist.advance()

    shown = slideshow_set.map()
    assert shown.corner.prompt_id == "id-2"
    assert (shown.seeds, shown.actions, shown.playing) == ((), (), ("corner", 0))


def test_looping_the_seeds_plays_the_row_round_under_a_map_that_holds_still():
    """The row becomes the pass, in the row's own order and starting on the
    slide on screen; as it plays the lit cell walks the row while the corner
    stays put — and the column is the lit seed's own, since every seed has
    other configurations of its own."""
    slideshow_set, dealt = _mapped()

    assert slideshow_set.start_loop("seed") is True
    assert dealt == [True]                       # the slide on screen stayed
    assert _ids(slideshow_set.playlist.items) == ["id-1", "id-1b", "id-1c"]

    slideshow_set.playlist.advance()
    shown = slideshow_set.map()
    assert shown.corner.prompt_id == "id-1"      # the loop's anchor, not the slide
    assert _ids(shown.seeds) == ["id-1b", "id-1c"]
    assert shown.playing == ("seed", 0)
    assert shown.loop == "seed"
    assert _ids(shown.actions) == ["id-1bx"]      # the lit seed's column


def test_ending_the_loop_goes_back_to_browsing_with_the_slide_kept():
    """The browse resumes underneath; a slide the loop wandered onto that the
    set never held plays out first, and the browse is what comes next."""
    slideshow_set, dealt = _mapped()
    slideshow_set.start_loop("seed")
    slideshow_set.playlist.advance()
    dealt.clear()

    assert slideshow_set.end_loop() is True

    assert dealt == [True]
    assert _ids(slideshow_set.playlist.items) == ["id-1b", "id-1", "id-2", "id-3"]
    assert slideshow_set.current_prompt_id() == "id-1b"
    assert slideshow_set.map().loop == ""
    assert slideshow_set.end_loop() is False          # nothing left to end


def test_a_slide_taken_away_leaves_the_loop_it_was_in():
    """A running loop is drawn on the map from the pool it was dealt, not from
    the library — so an image taken away has to leave that pool too, or the map
    goes on drawing it beside the ones still there."""
    slideshow_set, _dealt = _mapped()
    slideshow_set.start_loop("seed")

    slideshow_set.forget_id("id-1b")

    assert [slide.prompt_id for slide in slideshow_set.loop.pool] == ["id-1", "id-1c"]
    assert [cell.prompt_id for cell in slideshow_set.map().seeds] == ["id-1c"]


def test_a_loop_down_to_one_slide_is_one_to_end():
    """A cull can leave a loop holding only the slide on screen, and stepping
    round a row of one is that same image again — so a forward step ends it."""
    slideshow_set, _dealt = _mapped()
    slideshow_set.start_loop("seed")
    slideshow_set.playlist.drop("id-1b")
    slideshow_set.playlist.drop("id-1c")

    assert slideshow_set.end_a_loop_of_one() is True
    assert slideshow_set.loop is None


def test_a_loop_with_somewhere_to_go_is_not_one_to_end():
    """The row is what the forward step walks while it still holds another
    slide; only a row down to the one on screen is the dead end that ends it."""
    slideshow_set, _dealt = _mapped()
    slideshow_set.start_loop("seed")

    assert slideshow_set.end_a_loop_of_one() is False
    assert slideshow_set.loop is not None


def test_the_loop_key_steps_the_lock_then_seeds_then_configs_then_off_and_round_again():
    slideshow_set, _dealt = _mapped()

    assert slideshow_set.step_loop(locked=False) == LOCK
    assert slideshow_set.step_loop(locked=True) == SEED
    assert slideshow_set.step_loop(locked=False) == ACTION
    assert _ids(slideshow_set.playlist.items) == ["id-1", "id-1x"]
    assert slideshow_set.step_loop(locked=False) == OFF
    assert slideshow_set.step_loop(locked=False) == LOCK


def test_a_loop_down_the_column_plays_the_whole_group_not_one_of_each_act():
    """The column steps between acts, so twins of one act share a row; the
    loop is the image and every video of it, and its map is the loop."""
    twin = Slide("one-y.png", "image", "id-1y")
    whole = lambda pid: NavMapNeighbors(  # noqa: E731
        column=tuple(NavMapRow(slide, "dawn") for slide in _ACTIONS.get(pid, ())),
        group=(*_ACTIONS.get(pid, ()), twin) if pid == "id-1" else ())
    slideshow_set, _dealt = _set(neighbors=whole)

    assert slideshow_set.start_loop("action") is True

    assert _ids(slideshow_set.playlist.items) == ["id-1", "id-1x", "id-1y"]
    assert _ids(slideshow_set.map().actions) == ["id-1x", "id-1y"]


def test_an_axis_with_nothing_to_loop_is_stepped_over():
    seeds_only = lambda pid: NavMapNeighbors(seeds=_SEEDS.get(pid, ()))  # noqa: E731
    slideshow_set, _dealt = _set(neighbors=seeds_only)

    assert slideshow_set.step_loop(locked=True) == SEED
    assert slideshow_set.step_loop(locked=False) == OFF


def test_with_nothing_on_either_axis_the_loop_key_locks_and_lets_go():
    slideshow_set, dealt = _set()

    assert slideshow_set.step_loop(locked=False) == LOCK
    assert slideshow_set.step_loop(locked=True) == OFF
    assert dealt == []


def test_more_seeds_widens_the_row_and_loops_what_it_becomes():
    beyond = (Slide("far.png", "image", "id-far"),)
    slideshow_set, _dealt = _mapped(widen=lambda pid: beyond if pid == "id-1" else ())

    assert slideshow_set.more_seeds() is True

    shown = slideshow_set.map()
    assert _ids(shown.seeds) == ["id-1b", "id-1c", "id-far"]
    assert shown.loop == "seed"


def test_more_seeds_with_nothing_beyond_the_row_changes_nothing():
    slideshow_set, dealt = _mapped(widen=lambda pid: ())

    assert slideshow_set.more_seeds() is False
    assert dealt == []
    assert slideshow_set.loop is None


def test_a_map_cell_the_pass_never_held_is_spliced_in_and_jumped_to():
    slideshow_set, _dealt = _mapped()
    stranger = slideshow_set.slide_for_path("one-x.png")

    assert stranger.prompt_id == "id-1x"
    assert slideshow_set.jump_to(stranger) is True
    assert slideshow_set.current_prompt_id() == "id-1x"
    assert _ids(slideshow_set.playlist.items) == ["id-1", "id-2", "id-3", "id-1x"]
    assert slideshow_set.map().corner.prompt_id == "id-1x"    # the map re-homed


def test_a_slide_the_set_took_in_past_its_switches_is_still_found_by_its_file():
    slideshow_set, _dealt = _set(hud=HudFacts(favorite_ids={"id-1", "id-2", "id-3"}))
    slideshow_set.set_filters(SlideshowFilters(favorites=True))
    slideshow_set.remember(Slide("four.png", "image", "id-4"))

    found = slideshow_set.slide_for_path("four.png")

    assert found is not None
    assert found.prompt_id == "id-4"


def test_a_jump_off_a_loops_axis_ends_the_loop():
    slideshow_set, _dealt = _mapped()
    slideshow_set.start_loop("seed")

    slideshow_set.jump_to(slideshow_set.slide_for_path("one-x.png"))

    assert slideshow_set.loop is None
    assert slideshow_set.current_prompt_id() == "id-1x"


def test_navigation_walks_the_row_and_the_column_as_rings_headed_by_the_corner():
    slideshow_set, _dealt = _mapped()

    assert slideshow_set.nav_target("right").prompt_id == "id-1b"
    assert slideshow_set.nav_target("left").prompt_id == "id-1c"
    assert slideshow_set.nav_target("down").prompt_id == "id-1x"
    assert slideshow_set.nav_target("up").prompt_id == "id-1x"

    slideshow_set.playlist.advance()                  # id-2 has nothing around it
    assert slideshow_set.nav_target("right") is None


def test_navigation_off_a_lit_seed_dives_into_that_seeds_own_column():
    slideshow_set, _dealt = _mapped()
    slideshow_set.start_loop("seed")
    slideshow_set.playlist.advance()                  # the lit cell is id-1b

    assert slideshow_set.nav_target("right").prompt_id == "id-1c"
    assert slideshow_set.nav_target("left").prompt_id == "id-1"     # back to the corner
    assert slideshow_set.nav_target("down").prompt_id == "id-1bx"


def test_a_switch_ends_a_loop_and_deals_the_browse():
    slideshow_set, _dealt = _mapped(hud=HudFacts(favorite_ids={"id-2"}))
    slideshow_set.start_loop("seed")

    slideshow_set.set_filters(SlideshowFilters(favorites=True))

    assert slideshow_set.loop is None
    assert _ids(slideshow_set.playlist.items) == ["id-2"]


def test_a_set_with_nothing_in_it_has_nothing_to_map_loop_widen_or_walk():
    slideshow_set, dealt = _set(items=[], neighbors=_neighbors, widen=lambda pid: ())

    assert slideshow_set.map() is None
    assert slideshow_set.step_loop(locked=False) == LOCK
    assert slideshow_set.more_seeds() is False
    assert slideshow_set.set_act_filter("fox") is False
    assert slideshow_set.nav_target("right") is None
    assert dealt == []


def test_a_slide_that_joined_the_pass_mid_loop_is_mapped_as_itself():
    """A generation landing while a row loops is played in its turn, and the
    map re-homes on it rather than lighting a cell of a row it is not in."""
    slideshow_set, _dealt = _mapped()
    slideshow_set.start_loop("seed")
    slideshow_set.playlist.add(Slide("new.png", "image", "id-new"))
    slideshow_set.playlist.advance()

    shown = slideshow_set.map()

    assert shown.corner.prompt_id == "id-new"
    assert (shown.playing, shown.loop) == (("corner", 0), "")


_ROW = [("one.png", "image", "id-1"), ("one-b.png", "image", "id-1b"),
        ("one-c.png", "image", "id-1c")]


def _row_mates(prompt_id):
    """Every slide of the one row is every other's seed, as a folder's images are."""
    in_the_row = any(item[2] == prompt_id for item in _ROW)
    return NavMapNeighbors(seeds=tuple(Slide.of(item) for item in _ROW
                                    if in_the_row and item[2] != prompt_id), label="fox")


def test_a_set_that_is_one_seed_row_opens_as_that_row_looping():
    """A folder played as a slideshow is its seeds played round and round, which is
    all a seed loop is — so the map says so from the first slide."""
    slideshow_set, dealt = _set(items=_ROW, neighbors=_row_mates)

    shown = slideshow_set.map()

    assert (shown.loop, shown.playing) == ("seed", ("corner", 0))
    assert _ids(shown.seeds) == ["id-1b", "id-1c"]
    assert dealt == []                           # it was already playing the row


def test_a_row_opened_part_way_along_lights_its_cells_in_the_order_they_play():
    slideshow_set, _dealt = _set(items=_ROW, neighbors=_row_mates, start=1)

    slideshow_set.playlist.advance()
    shown = slideshow_set.map()

    assert _ids((shown.corner, *shown.seeds)) == ["id-1b", "id-1c", "id-1"]
    assert shown.playing == ("seed", 0)


def test_a_set_with_a_slide_from_outside_the_row_opens_browsing():
    slideshow_set, _dealt = _set(items=[*_ROW, ("two.png", "image", "id-2")], neighbors=_row_mates)

    assert slideshow_set.map().loop == ""


def test_a_lone_slide_is_no_loop():
    slideshow_set, _dealt = _set(items=_ROW[:1], neighbors=_row_mates)

    assert slideshow_set.map().loop == ""


def test_the_loop_button_over_a_row_opened_looping_ends_the_loop():
    slideshow_set, _dealt = _set(items=_ROW, neighbors=_row_mates)

    assert slideshow_set.end_loop() is True
    assert slideshow_set.map().loop == ""


def _falls_back(answer=True):
    """A surface that takes another set when asked, and says whether it did."""
    asked = []

    def fall_back():
        asked.append(True)
        return answer

    return fall_back, asked


def test_a_loop_over_a_set_that_is_one_row_ends_somewhere_else_entirely():
    slideshow_set, dealt = _set(items=_ROW, neighbors=_row_mates)
    fall_back, asked = _falls_back()

    assert slideshow_set.end_loop(fall_back) is True

    assert asked == [True]
    assert slideshow_set.loop is None
    assert dealt == []          # the set fallen back to is dealt by the surface


def test_a_loop_with_a_set_under_it_ends_into_that_set_rather_than_falling_back():
    slideshow_set, dealt = _mapped()
    slideshow_set.start_loop("seed")
    fall_back, asked = _falls_back()
    dealt.clear()

    assert slideshow_set.end_loop(fall_back) is True

    assert asked == []
    assert dealt == [True]
    assert _ids(slideshow_set.playlist.items) == ["id-1", "id-2", "id-3"]


def test_a_loop_whose_way_out_has_nothing_to_play_ends_into_the_set_as_ever():
    slideshow_set, dealt = _set(items=_ROW, neighbors=_row_mates)
    fall_back, asked = _falls_back(answer=False)

    assert slideshow_set.end_loop(fall_back) is True

    assert asked == [True]
    assert dealt == [True]
    assert _ids(slideshow_set.playlist.items) == ["id-1", "id-1b", "id-1c"]


def test_the_loop_key_stepped_off_a_row_falls_back_the_same_way():
    slideshow_set, _dealt = _set(items=_ROW, neighbors=_row_mates)
    fall_back, asked = _falls_back()

    assert slideshow_set.step_loop(locked=False, fall_back=fall_back) == OFF

    assert asked == [True]


def test_a_set_taken_up_under_the_slide_on_screen_plays_on_from_it():
    slideshow_set, dealt = _set()
    slideshow_set.playlist.jump_to(1)
    wider = [("two.png", "image", "id-2"), ("nine.png", "image", "id-9")]

    slideshow_set.reorder(wider, latest=True, keep_slide=True)

    assert dealt == [True]
    assert slideshow_set.current_prompt_id() == "id-2"
    assert _pass(slideshow_set) == ["id-2", "id-9"]


def test_a_set_taken_up_under_the_slide_is_no_row_to_be_dealt_as_a_loop():
    slideshow_set, _dealt = _set(items=_ROW, neighbors=_row_mates)

    slideshow_set.reorder(_ROW, latest=True, keep_slide=True)
    assert slideshow_set.loop is None

    slideshow_set.reorder(_ROW, latest=True)
    assert slideshow_set.loop is not None


def test_a_generation_landing_in_a_row_that_is_looping_joins_the_loop():
    slideshow_set, _dealt = _set(items=_ROW[:2], neighbors=_row_mates)
    landed = Slide.of(_ROW[2])

    slideshow_set.remember(landed)
    slideshow_set.playlist.add(landed)
    slideshow_set.playlist.advance()

    shown = slideshow_set.map()
    assert _ids((shown.corner, *shown.seeds)) == ["id-1", "id-1b", "id-1c"]
    assert (shown.loop, shown.playing) == ("seed", ("seed", 1))


# --- picking a closed slideshow back up -------------------------------------

def test_a_loop_is_left_naming_what_it_plays_with_the_slide_it_began_on_first():
    slideshow_set, _dealt = _mapped()
    slideshow_set.start_loop("seed")
    slideshow_set.playlist.advance()

    left = slideshow_set.state(locked=False, version_index=0)

    assert (left.loop, left.loop_pool) == ("seed", ("id-1", "id-1b", "id-1c"))
    assert left.current == "id-1b"


def test_a_loop_picked_back_up_plays_its_own_slides_from_the_one_it_was_left_on():
    beyond = (Slide("far.png", "image", "id-far"),)
    closed, _dealt = _mapped(widen=lambda pid: beyond if pid == "id-1" else ())
    closed.more_seeds()
    for _ in range(3):
        closed.playlist.advance()

    reopened, _dealt = _mapped(slides=slides_named(*closed.playlist.items))
    assert reopened.resume(closed.state(locked=False, version_index=0)) is True

    assert reopened.current_prompt_id() == "id-far"
    assert reopened.map() == closed.map()


# --- the act filter: the map's row buttons, and the session's spoken acts ------

_NAMED_FOR = {"id-1": "Source image, alpha", "id-2": "beta", "id-3": "alpha"}


def _acts(prompt_ids):
    return {prompt_id: _NAMED_FOR.get(prompt_id, "") for prompt_id in prompt_ids}


def _filterable(**fields):
    return _set(acts=_acts, **fields)


def test_an_act_filter_narrows_the_pass_to_what_is_named_for_that_act():
    slideshow_set, dealt = _filterable()

    assert slideshow_set.set_act_filter("alpha") is True

    assert _ids(slideshow_set.playlist.items) == ["id-1", "id-3"]
    assert slideshow_set.filters.act == "alpha"
    assert dealt == [True]                      # the slide on screen shows that act


def test_a_filter_that_would_leave_nothing_is_refused_and_the_pass_left_alone():
    """A filter that selected nothing is a dead end, not a mode: the set plays
    on, and the row's button stays dark."""
    slideshow_set, dealt = _filterable()

    assert slideshow_set.set_act_filter("gamma") is False

    assert (slideshow_set.filters.act, dealt, len(slideshow_set.playlist)) == ("", [], 3)


def test_a_filter_naming_two_acts_keeps_only_what_is_named_for_both():
    """Set from a row carrying two acts it names both, and only a generation
    carrying both answers it — the rule the HUD lights its rows by."""
    slideshow_set, _dealt = _filterable()

    assert slideshow_set.set_act_filter("source image, alpha") is True

    assert _ids(slideshow_set.playlist.items) == ["id-1"]


def test_filtering_to_the_act_on_screen_narrows_to_what_its_row_is_named_for():
    """A session's spoken "filter", said of a shape: the act read off the item
    on screen rather than spoken, the way its map row's button would post it."""
    slideshow_set, _dealt = _filterable()
    slideshow_set.playlist.jump_to(2)

    assert narrow_to_the_act_on_screen(slideshow_set) == ("Filter: 'alpha' (2)", True)
    assert _ids(slideshow_set.playlist.items) == ["id-1", "id-3"]


def test_an_item_named_for_no_act_says_so_and_leaves_the_pass_alone():
    """Rather than lifting the filter, which is what nothing posted to a row's
    button means."""
    slideshow_set, _dealt = _set(acts=lambda ids: dict.fromkeys(ids, ""))

    said, narrowed = narrow_to_the_act_on_screen(slideshow_set)

    assert (said, narrowed) == ("No act for this one", False)
    assert (slideshow_set.filters.act, len(slideshow_set.playlist)) == ("", 3)


def test_a_reset_drops_the_act_filter_with_the_other_switches():
    slideshow_set, dealt = _filterable()
    slideshow_set.set_act_filter("beta")
    dealt.clear()

    assert slideshow_set.drop_the_filters() is True

    assert (slideshow_set.filters.act, len(slideshow_set.playlist), dealt) == ("", 3, [False])


def test_a_landing_is_asked_about_afresh_because_it_can_rename_what_was_there():
    """A video landing makes its image a source, so what the library said
    before it landed is not what a filter may go on matching by."""
    named_for = dict(_NAMED_FOR)
    slideshow_set, _dealt = _set(acts=lambda ids: {pid: named_for.get(pid, "") for pid in ids})
    slideshow_set.set_act_filter("alpha")
    assert slideshow_set.passes(Slide("two.png", "image", "id-2")) is False

    named_for["id-2"] = "Source image, alpha"
    slideshow_set.remember(Slide("four.mp4", "video", "id-4"))

    assert slideshow_set.passes(Slide("two.png", "image", "id-2")) is True


def test_a_configuration_rows_button_is_told_from_an_acts_by_the_row_itself():
    """Half the column is configurations and half is acts, and the two are
    pressed differently — so the map says which a row is rather than leaving it
    to be guessed from the words in its margin."""
    a_configuration = Slide("one-x.png", "image", "id-1x")
    an_act = Slide("one-y.png", "image", "id-1y")
    both = lambda pid: NavMapNeighbors(  # noqa: E731
        column=(NavMapRow(a_configuration, "E629425B", configuration=True),
                NavMapRow(an_act, "alpha")) if pid == "id-1" else ())
    slideshow_set, _dealt = _set(neighbors=both)

    assert slideshow_set.configuration_row("e629425b") is a_configuration
    assert slideshow_set.configuration_row("alpha") is None
    assert slideshow_set.configuration_row("nobody") is None


def test_the_frame_of_an_image_being_made_is_its_newest():
    slideshow_set, _dealt = _set()
    plain, waiting, enhancing = (Slide.of(item) for item in _ITEMS)
    live = Slide(b"run-frame", LIVE, "id-run")

    slideshow_set.note_enhancing({"id-2": "queued", "id-3": "running"},
                                 frames={"id-3": b"enhance-frame"})

    assert slideshow_set.frame_being_made_of(enhancing) == b"enhance-frame"
    assert slideshow_set.frame_being_made_of(waiting) is None
    assert slideshow_set.frame_being_made_of(plain) is None
    assert slideshow_set.frame_being_made_of(live) == b"run-frame"

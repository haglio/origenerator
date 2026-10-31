from __future__ import annotations

import json

import pytest
from PyQt6.QtCore import (
    QEvent,
    Qt,
)
from PyQt6.QtGui import (
    QKeyEvent,
)

from origenerator import (
    gallery,
)
from origenerator.gallery.collection import (
    ENHANCED_KEY,
    EXPERIMENTS_KEY,
    FAVORITES_KEY,
    LATEST_KEY,
)
from origenerator.gallery.sides import LANDSCAPE
from origenerator.gui.folder_tile import FolderTile
from origenerator.gui.gallery_view import GalleryView
from origenerator.gui.motion_panel import MotionPanel
from origenerator.gui.slideshow_hud import slideshow_hud_model
from origenerator.orientation import key_holds, oriented_key
from origenerator.slideshow import LIVE
from origenerator.voice.app_commands import AppCommand
from tests import gestures
from tests.gallery_view_support import (
    _CTRL,
    _NO_MOD,
    _WAN_I2V,
    MODE_VERBS,
    FakeActions,
    FakeDB,
    _a_slideshow_standing_on_its_own,
    _alls,
    _at,
    _click_tile,
    _collection,
    _collection_row,
    _double_click_slideshow,
    _drawn,
    _enhanceable_db,
    _enhanced_image,
    _experiment_row,
    _i2v_video,
    _image,
    _image_workflow,
    _in_view,
    _key,
    _keys_are_the_gallerys,
    _on_screen,
    _open_latest,
    _open_leaf,
    _press_enter,
    _reroll_client,
    _resolve_by_id,
    _row,
    _running_row,
    _scroll_bar,
    _seeded_db,
    _select_first_leaf,
    _set_enhance,
    _top_level,
)
from tests.marked_words import words
from tests.slideshow_hud_support import funestra_of, hud_button_names, hud_targets
from tests.slideshow_support import ahead

pytestmark = pytest.mark.usefixtures("_stub_preview_resolution")


# --- slideshow: play a folder's or a collection's media fullscreen ----------


def test_slideshow_opens_the_folders_media(qtbot, monkeypatch):
    _resolve_by_id(monkeypatch)
    view = GalleryView(FakeDB([_image("i1", "a cat", 50, 1), _image("i2", "a cat", 50, 2)]))
    qtbot.addWidget(view)
    view.refresh()
    _select_first_leaf(view)

    view._slideshows.start()

    qtbot.addWidget(view._slideshows.showing.shown)
    assert len(view._slideshows.showing._set.playlist) == 2  # both variations queued to play
    view._slideshows.showing.close()


def test_the_slideshow_begins_on_whichever_item_is_picked_in_the_folder(qtbot, monkeypatch):
    _resolve_by_id(monkeypatch)
    view = GalleryView(FakeDB([_image(f"i{n}", "a cat", 50, n) for n in (1, 2, 3)]))
    qtbot.addWidget(view)
    view.refresh()
    _open_leaf(view)

    for picked in view.listed_prompt_ids():
        view._browser.apply_selection(picked, _NO_MOD)
        view._slideshows.start()
        slideshow = view._slideshows.showing
        qtbot.addWidget(slideshow.shown)
        assert slideshow._set.playlist.current().prompt_id == picked
        slideshow.close()


def test_an_item_picked_while_a_slideshow_sits_minimized_is_where_the_button_begins_it(
        qtbot, monkeypatch):
    _resolve_by_id(monkeypatch)
    view = GalleryView(FakeDB([_image(f"i{n}", "a cat", 50, n) for n in (1, 2, 3)]))
    qtbot.addWidget(view)
    view.refresh()
    _open_leaf(view)
    view._bank.slideshow.click()
    minimized = view._slideshows.showing
    qtbot.addWidget(minimized.shown)
    minimized.shown.showMinimized()
    picked = next(pid for pid in view.listed_prompt_ids()
                  if pid != minimized._set.playlist.current().prompt_id)
    view._browser.apply_selection(picked, _NO_MOD)

    view._bank.slideshow.click()

    assert view._slideshows.showing._set.playlist.current().prompt_id == picked
    view._slideshows.showing.close()


def test_with_two_items_picked_the_slideshow_comes_back_to_where_the_last_one_closed(
        qtbot, monkeypatch):
    _resolve_by_id(monkeypatch)
    view = GalleryView(FakeDB([_image(f"i{n}", "a cat", 50, n) for n in (1, 2, 3)]))
    qtbot.addWidget(view)
    view.refresh()
    _open_leaf(view)
    view._slideshows.start()
    last = view._slideshows.showing
    qtbot.addWidget(last.shown)
    closed_on = last._set.playlist.current().prompt_id
    last.close()
    elsewhere = [pid for pid in view.listed_prompt_ids() if pid != closed_on]
    view._browser.apply_selection(elsewhere[0], _NO_MOD)
    view._browser.apply_selection(elsewhere[1], _CTRL)

    view._slideshows.start()

    slideshow = view._slideshows.showing
    qtbot.addWidget(slideshow.shown)
    assert slideshow._set.playlist.current().prompt_id == closed_on
    slideshow.close()


def test_the_item_picked_comes_first_though_another_in_the_folder_is_being_enhanced(
        qtbot, monkeypatch):
    _resolve_by_id(monkeypatch)
    view = GalleryView(FakeDB([_image(f"i{n}", "a cat", 50, n) for n in (1, 2, 3)]))
    qtbot.addWidget(view)
    view.refresh()
    _open_leaf(view)
    view._slideshows.start()
    last = view._slideshows.showing
    qtbot.addWidget(last.shown)
    last.close()
    (picked,) = view.selected_prompt_ids()   # the slide it closed on
    enhancing = next(pid for pid in view.listed_prompt_ids() if pid != picked)
    view._slideshows.note_enhancing({enhancing: "running"})

    view._slideshows.start()

    slideshow = view._slideshows.showing
    qtbot.addWidget(slideshow.shown)
    assert slideshow._set.playlist.current().prompt_id == picked
    slideshow.close()


def _standalone_slideshow(qtbot, monkeypatch):
    """A fullscreen slideshow of two images, opened with no session under it."""
    _resolve_by_id(monkeypatch)
    view = GalleryView(FakeDB([_image("i1", "a cat", 50, 1), _image("i2", "a cat", 50, 2)]))
    qtbot.addWidget(view)
    view.refresh()
    _select_first_leaf(view)
    view._slideshows.start()
    qtbot.addWidget(view._slideshows.showing.shown)
    funestra_of(view._slideshows.showing.shown)
    return view._slideshows.showing


def test_a_standalone_slideshow_wears_the_funestras_own_hud(qtbot, monkeypatch):
    # Nothing about a slideshow is different for not being inside a session: it is
    # the same set played the same way, so it wears the same panel a region
    # slideshow wears — and the view's own furnishings come off, because the map
    # says all of it.

    slideshow = _standalone_slideshow(qtbot, monkeypatch)

    assert {"prev", "next", "lock", "trash"} <= set(hud_button_names(slideshow.shown))
    slideshow.close()


def test_a_standalone_hud_draws_no_mode_row_and_no_minimize(qtbot, monkeypatch):
    # The mode pair hands a region back to the Funestra under it.  There is no
    # Funestra under a standalone slideshow and no session to tell, so the row is not
    # drawn rather than drawn dead.

    slideshow = _standalone_slideshow(qtbot, monkeypatch)

    names = hud_button_names(slideshow.shown)
    assert MODE_VERBS.isdisjoint(names)
    assert "minimize" not in names
    slideshow.close()


def test_a_standalone_huds_transport_lands_on_the_slideshow_itself(qtbot, monkeypatch):
    # Hosted, prev/next/lock/trash go out on the session's command file and come
    # back through its dispatch onto this very slideshow.  With no file to post on,
    # the press reaches the slideshow directly instead of being swallowed.

    slideshow = _standalone_slideshow(qtbot, monkeypatch)
    side = slideshow.shown.hud_side
    opened = slideshow._set.playlist.current()

    slideshow.shown.press(f"{side}_next")
    assert slideshow._set.playlist.current() != opened

    slideshow.shown.press(f"{side}_lock")
    assert slideshow.locked is True
    slideshow.close()


def test_starting_a_slideshow_while_the_last_one_sits_minimized_puts_it_back_on_screen(
        qtbot, monkeypatch):
    view, slideshow = _a_slideshow_standing_on_its_own(qtbot, monkeypatch)
    view.resize(1200, 800)
    with qtbot.waitExposed(view):
        view.show()
    slideshow.shown.showMinimized()   # from the taskbar, which still minimizes any window
    assert slideshow.shown.isMinimized()

    gestures.click(view._bank.slideshow, view._bank.slideshow.rect().center())

    assert view._slideshows.showing is slideshow
    assert not slideshow.shown.isMinimized()
    slideshow.close()


def test_wasd_reach_a_standalone_slideshow_past_the_gallerys_own_key_filter(qtbot, monkeypatch):
    slideshow = _standalone_slideshow(qtbot, monkeypatch)
    opened = slideshow._set.playlist.current()

    qtbot.keyClick(slideshow.shown, Qt.Key.Key_D)
    assert slideshow._set.playlist.current() != opened

    qtbot.keyClick(slideshow.shown, Qt.Key.Key_A)
    assert slideshow._set.playlist.current() == opened
    slideshow.close()


def test_a_standalone_huds_order_pair_plays_the_library_of_its_shape(qtbot, monkeypatch):
    slideshow = _standalone_slideshow(qtbot, monkeypatch)
    played = []

    for order in ("latest", "shuffle"):
        slideshow.shown.press(f"{slideshow.shown.hud_side}_{order}")
        playlist = slideshow._set.playlist
        played.append((slideshow.hud_order_label,
                       sorted(playlist.items[index][2] for index in playlist.order)))

    # Latest plays one of a sitting's run of one configuration, and these two
    # images are such a run; Shuffle plays the shape's whole library.
    assert played == [("Latest", ["i1"]), ("Shuffle", ["i1", "i2"])]
    slideshow.close()


def test_a_video_asked_for_while_the_slideshow_plays_is_made(qtbot, monkeypatch, tmp_path):
    _resolve_by_id(monkeypatch)
    client = _reroll_client()
    view = GalleryView(_seeded_db(tmp_path), client=client)
    qtbot.addWidget(view)
    view.refresh()
    _select_first_leaf(view)
    view._slideshows.start()
    qtbot.addWidget(view._slideshows.showing.shown)

    video = view._jobs.start_prepared("k", _WAN_I2V, _WAN_I2V.default_params())

    assert [call.args[1] for call in client.submit_job.call_args_list] == [video]


def test_locking_an_image_makes_its_waiting_enhancement_the_next_one_made(
        qtbot, tmp_path, monkeypatch):
    _resolve_by_id(monkeypatch)
    client = _reroll_client()
    view = GalleryView(_enhanceable_db(tmp_path, count=3), client=client)
    qtbot.addWidget(view)
    view.refresh()
    _select_first_leaf(view)
    view._slideshows.start()
    slideshow = view._slideshows.showing
    qtbot.addWidget(slideshow.shown)
    funestra_of(slideshow.shown)
    on_screen = slideshow.voice_target()
    view.enhance_items([on_screen, *({"g0", "g1", "g2"} - {on_screen})])

    slideshow.slideshow_toggle_lock()
    slideshow.tick()

    (wanted,) = view._enhance.jobs_targeting([view.row_for(on_screen)])
    assert view._jobs.queue_order[0] == wanted.prompt_id
    assert client.submit_job.call_args_list[-1].args[1] == wanted.prompt_id
    slideshow.close()


def test_the_slideshow_button_waits_until_there_is_something_to_play(qtbot):
    # A folder gets its node the moment a generation starts, so this one has a
    # row and no image. A button offering a slideshow that opens nothing is worse
    # than no button: it reappears once the first item lands.
    view = GalleryView(FakeDB([_running_row("in_flight", prompt="a cat")]))
    qtbot.addWidget(view)
    view.refresh()
    _select_first_leaf(view)

    assert view._bank.slideshow.isHidden()


def test_slideshow_button_follows_what_is_on_screen(qtbot, monkeypatch):
    _resolve_by_id(monkeypatch)
    db = FakeDB([_image("i1", "a cat", 50, 1)])
    db.set_generation_favorite("i1", True)
    view = GalleryView(db)
    qtbot.addWidget(view)
    view.refresh()
    _select_first_leaf(view)
    assert not view._bank.slideshow.isHidden()          # a folder with media offers it
    assert "this folder" in view._bank.slideshow.toolTip()

    # The collections hold media too, so each plays as a folder does...
    view._tree.setCurrentItem(_collection(view, LATEST_KEY))
    assert not view._bank.slideshow.isHidden()
    assert "Latest" in view._bank.slideshow.toolTip()
    view._tree.setCurrentItem(_collection(view, FAVORITES_KEY))
    assert not view._bank.slideshow.isHidden()
    assert "Favorites" in view._bank.slideshow.toolTip()

    # ...while a collection holding nothing at all doesn't offer one.
    view._tree.setCurrentItem(_collection(view, EXPERIMENTS_KEY))
    assert view._bank.slideshow.isHidden()


def test_a_slideshow_after_one_of_the_favorites_collection_is_not_held_to_the_favorites(qtbot,
                                                                               monkeypatch):
    _resolve_by_id(monkeypatch)
    view = GalleryView(FakeDB([_image("i1", "a cat", 50, 1),
                               _row("i2", "sdxl_t2i",
                                    {"positive_prompt": "a cat", "steps": 50, "seed": 2},
                                    "sdxl_t2i_i2.png", starred=1)]))
    qtbot.addWidget(view)
    view.refresh()
    view._tree.setCurrentItem(_collection(view, FAVORITES_KEY))
    view._slideshows.start()
    qtbot.addWidget(view._slideshows.showing.shown)
    assert view._slideshows.showing.hud_favorites_filter
    view._slideshows.showing.close()

    _select_first_leaf(view)
    view._slideshows.start()

    slideshow = view._slideshows.showing
    qtbot.addWidget(slideshow.shown)
    assert not slideshow.hud_favorites_filter
    assert sorted(item[2] for item in slideshow._set.playlist._items) == ["i1", "i2"]
    slideshow.close()


def test_a_slideshow_of_enhanced_lights_enhanced_only_and_the_next_slideshow_does_not(
        qtbot, monkeypatch):
    _resolve_by_id(monkeypatch)
    view = GalleryView(FakeDB([_image("i1", "a cat", 50, 1),
                               _enhanced_image("i2", "a cat", 50, 2)]))
    qtbot.addWidget(view)
    view.refresh()
    view._tree.setCurrentItem(_collection(view, ENHANCED_KEY))
    view._slideshows.start()
    qtbot.addWidget(view._slideshows.showing.shown)
    assert view._slideshows.showing.hud_enhanced_mode
    view._slideshows.showing.close()

    _select_first_leaf(view)
    view._slideshows.start()

    slideshow = view._slideshows.showing
    qtbot.addWidget(slideshow.shown)
    assert not slideshow.hud_enhanced_mode
    assert sorted(item[2] for item in slideshow._set.playlist._items) == ["i1", "i2"]
    slideshow.close()


def test_favorites_begins_on_the_favorite_picked_there(qtbot, monkeypatch):
    _resolve_by_id(monkeypatch)
    view = GalleryView(FakeDB([
        _row(f"i{n}", "sdxl_t2i", {"positive_prompt": "a cat", "steps": 50, "seed": n},
             f"sdxl_t2i_i{n}.png", starred=1) for n in (1, 2, 3)]))
    qtbot.addWidget(view)
    view.refresh()
    view._tree.setCurrentItem(_collection(view, FAVORITES_KEY))
    view._slideshows.start()
    last = view._slideshows.showing
    qtbot.addWidget(last.shown)
    closed_on = last._set.playlist.current().prompt_id
    last.close()
    picked = next(pid for pid in view.listed_prompt_ids() if pid != closed_on)
    view._browser.apply_selection(picked, _NO_MOD)

    view._slideshows.start()

    slideshow = view._slideshows.showing
    qtbot.addWidget(slideshow.shown)
    assert slideshow._set.playlist.current().prompt_id == picked
    assert slideshow.hud_favorites_filter
    slideshow.close()


def test_slideshow_plays_the_latest_collection(qtbot, monkeypatch):
    _resolve_by_id(monkeypatch)
    view = GalleryView(FakeDB([_image("i1", "a cat", 50, 1), _i2v_video("v1", "styleA")]))
    qtbot.addWidget(view)
    view.refresh()
    view._tree.setCurrentItem(_collection(view, LATEST_KEY))

    view._slideshows.start()

    qtbot.addWidget(view._slideshows.showing.shown)
    assert len(view._slideshows.showing._set.playlist) == 2  # both recent generations queued
    view._slideshows.showing.close()


def test_a_slideshow_of_one_kinds_latest_plays_that_kind_alone(qtbot, monkeypatch):
    _resolve_by_id(monkeypatch)
    view = GalleryView(FakeDB([_image("i1", "a cat", 50, 1), _i2v_video("v1", "styleA")]))
    qtbot.addWidget(view)
    view.refresh()
    view._tree.setCurrentItem(_collection_row(_alls(view._tree)["Images"], "Latest"))

    view._slideshows.start()

    qtbot.addWidget(view._slideshows.showing.shown)
    assert [item[2] for item in view._slideshows.showing._set.playlist._items] == ["i1"]
    view._slideshows.showing.close()


def test_latest_begins_on_its_newest_whatever_is_picked_there(qtbot, monkeypatch):
    _resolve_by_id(monkeypatch)
    view = GalleryView(FakeDB([_image("i1", "a cat", 50, 1), _image("i2", "a dog", 50, 2)]))
    qtbot.addWidget(view)
    view.refresh()
    _open_latest(view)
    newest, older = view.listed_prompt_ids()
    view._browser.apply_selection(older, _NO_MOD)

    view._slideshows.start()

    slideshow = view._slideshows.showing
    qtbot.addWidget(slideshow.shown)
    assert slideshow._set.playlist.current().prompt_id == newest
    slideshow.close()


def test_the_enhanced_switch_narrows_a_slideshow_to_the_images_made_better(qtbot, monkeypatch):
    # A folder enhanced through carries both versions of everything, and a pass
    # of that is every image twice — the second time being the point.  The
    # switch is the slideshow's own, beside F-mode on the HUD it wears.
    _resolve_by_id(monkeypatch)
    view = GalleryView(FakeDB([_image("i1", "a cat", 50, 1),
                               _enhanced_image("i2", "a dog", 50, 2)]))
    qtbot.addWidget(view)
    view.refresh()
    _open_latest(view)
    view._slideshows.start()
    slideshow = view._slideshows.showing
    qtbot.addWidget(slideshow.shown)
    assert len(slideshow._set.playlist) == 2

    slideshow.toggle_enhanced_mode()

    assert [item[2] for item in slideshow._set.playlist._items] == ["i2"]
    slideshow.toggle_enhanced_mode()   # and back again, all of them
    assert len(slideshow._set.playlist) == 2
    slideshow.close()


def test_a_standalone_huds_enhanced_switch_narrows_the_slideshow(qtbot, monkeypatch):
    # The button sits beside F-mode on the HUD every slideshow wears, and pressing it
    # lands on the slideshow itself, hosted or not; the title names the cut.

    _resolve_by_id(monkeypatch)
    view = GalleryView(FakeDB([_image("i1", "a cat", 50, 1),
                               _enhanced_image("i2", "a dog", 50, 2)]))
    qtbot.addWidget(view)
    view.refresh()
    _open_latest(view)
    view._slideshows.start()
    slideshow = view._slideshows.showing
    qtbot.addWidget(slideshow.shown)
    names = hud_button_names(slideshow.shown)
    assert names.index("enhanced") == names.index("fmode") + 1

    slideshow.shown.press(f"{slideshow.shown.hud_side}_enhanced")

    assert slideshow.hud_enhanced_mode is True
    assert [item[2] for item in slideshow._set.playlist._items] == ["i2"]
    model = slideshow_hud_model(slideshow.shown.hud_side, slideshow, hosted=False)
    lit = {button.command: button.lit for row in model.rows for button in row}
    assert lit[f"{slideshow.shown.hud_side}_enhanced"]
    assert "Enhanceds" in model.title
    slideshow.close()


def test_a_generation_that_lands_unenhanced_stays_out_of_a_narrowed_slideshow(qtbot, monkeypatch):
    # The slideshow takes in what lands while it runs; the switch decides that too,
    # or a narrowed slideshow would fill back up with the very rows it left out.
    _resolve_by_id(monkeypatch)
    view = GalleryView(FakeDB([_enhanced_image("i2", "a cat", 50, 2)]))
    qtbot.addWidget(view)
    view.refresh()
    _open_latest(view)
    view._slideshows.start()
    slideshow = view._slideshows.showing
    qtbot.addWidget(slideshow.shown)
    slideshow.set_enhanced_mode(True)
    plain, better = _image("i3", "a cat", 50, 3), _enhanced_image("i4", "a cat", 50, 4)
    monkeypatch.setattr(view._slideshows, "rows_at", lambda location: [plain, better])

    view._slideshows.note_finished(plain)
    view._slideshows.note_finished(better)

    assert sorted(item[2] for item in slideshow._set.playlist._items) == ["i2", "i4"]
    slideshow.clear_modes()
    assert sorted(item[2] for item in slideshow._set.playlist._items) == ["i2", "i3", "i4"]
    slideshow.close()


def test_clear_filter_puts_back_everything_the_switches_took(qtbot, monkeypatch):
    # With two switches on the HUD, the phrase has to mean both — which is what
    # it means on every satellite in this family.
    _resolve_by_id(monkeypatch)
    view = GalleryView(FakeDB([_image("i1", "a cat", 50, 1),
                               _row("i2", "sdxl_t2i",
                                    {"positive_prompt": "a dog", "steps": 50, "seed": 2,
                                     "enhance": True},
                                    "sdxl_t2i_i2.png", favorite=1)]))
    qtbot.addWidget(view)
    view.refresh()
    _open_latest(view)
    view._slideshows.start()
    slideshow = view._slideshows.showing
    qtbot.addWidget(slideshow.shown)
    slideshow.toggle_favorites_filter()
    slideshow.toggle_enhanced_mode()
    assert [item[2] for item in slideshow._set.playlist._items] == ["i2"]

    view._voice._run_app_command(AppCommand.FILTER_OFF)

    assert (slideshow.hud_favorites_filter, slideshow.hud_enhanced_mode) == (False, False)
    assert len(slideshow._set.playlist) == 2
    slideshow.close()


def test_filter_enhanced_turns_the_slideshows_switch_on_and_says_what_is_left(qtbot, monkeypatch):
    _resolve_by_id(monkeypatch)
    view = GalleryView(FakeDB([_image("i1", "a cat", 50, 1),
                               _enhanced_image("i2", "a dog", 50, 2)]))
    qtbot.addWidget(view)
    view.refresh()
    _open_latest(view)
    view._slideshows.start()
    slideshow = view._slideshows.showing
    qtbot.addWidget(slideshow.shown)

    view._voice._run_app_command(AppCommand.FILTER_ENHANCED)

    assert slideshow.hud_enhanced_mode is True
    assert "1 to play" in words(slideshow.shown._note)

    view._voice._run_app_command(AppCommand.FILTER_OFF)

    assert slideshow.hud_enhanced_mode is False
    assert "all of them" in words(slideshow.shown._note)
    slideshow.close()


def test_filter_enhanced_says_so_where_nothing_here_is_enhanced(qtbot, monkeypatch):
    _resolve_by_id(monkeypatch)
    view = GalleryView(FakeDB([_image("i1", "a cat", 50, 1)]))
    qtbot.addWidget(view)
    view.refresh()
    _open_latest(view)
    view._slideshows.start()
    slideshow = view._slideshows.showing
    qtbot.addWidget(slideshow.shown)

    view._voice._run_app_command(AppCommand.FILTER_ENHANCED)

    assert slideshow.hud_enhanced_mode is False
    assert "nothing here is enhanced" in words(slideshow.shown._note)
    slideshow.close()


def test_filter_enhanced_needs_a_slideshow_to_narrow(qtbot, monkeypatch):
    # The switch is a slideshow's: with none up there is nothing for the word to
    # narrow, and it says so rather than arming something for later.
    _resolve_by_id(monkeypatch)
    view = GalleryView(FakeDB([_enhanced_image("i2", "a cat", 50, 2)]))
    qtbot.addWidget(view)
    view.refresh()
    _open_latest(view)

    view._voice._run_app_command(AppCommand.FILTER_ENHANCED)

    assert "needs a slideshow" in words(view._voice.status)
    assert not view._bank.slideshow.isHidden()   # everything is still there to play


def test_a_slideshow_wears_one_hud_with_the_device_on_it(qtbot, monkeypatch):
    # A slideshow used to float two: the Funestras' HUD over the set, and Genau's whole
    # console under it for the device.  Between them the status was said twice
    # and disagreed, and prev/next/lock/trash were drawn on both.  One panel
    # now -- the HUD, carrying the device's line, the readout and the two rows
    # that aim them.

    slideshow = _standalone_slideshow(qtbot, monkeypatch)
    assert slideshow.findChildren(MotionPanel) == []
    posted = [button.command for _rect, button in hud_targets(slideshow.shown).buttons]
    assert "robot_hand_cycle_shape" in posted   # the motion's row is on it
    assert any(command.endswith("_clip_seconds_up") for command in posted)  # and the pace's
    assert slideshow.shown._hud_model().drive is not None  # with the readout under them
    slideshow.close()


def test_slideshow_plays_the_experiments_collection(qtbot, monkeypatch):
    # Reviewing a batch of experiments is exactly what a slideshow is for: full
    # screen, one at a time, rather than squinting at a grid of thumbnails.
    _resolve_by_id(monkeypatch)
    view = GalleryView(FakeDB([
        _experiment_row("e1"),
        _experiment_row("e2", seed=10),
        _experiment_row("e3", verdict="up", seed=11),  # reviewed: out of the collection
    ]))
    qtbot.addWidget(view)
    view.refresh()
    view._tree.setCurrentItem(_collection(view, EXPERIMENTS_KEY))
    assert not view._bank.slideshow.isHidden()
    assert "Experiments" in view._bank.slideshow.toolTip()

    view._slideshows.start()

    qtbot.addWidget(view._slideshows.showing.shown)
    # What the collection shows, so the judged one stays out of the rotation.
    assert {item[2] for item in view._slideshows.showing._set.playlist._items} == {"e1", "e2"}
    view._slideshows.showing.close()


def test_condemning_an_experiment_in_a_slideshow_rejects_it(qtbot):
    # Up on an unreviewed experiment is the collection's Reject, not a plain delete:
    # the row survives to teach the policy what to steer away from.
    db = FakeDB([_experiment_row("e1"), _image("i1", "a cat", 50, 1)])
    actions = FakeActions()
    view = GalleryView(db, actions=actions)
    qtbot.addWidget(view)
    view.refresh()

    view.trash_generation("e1")
    view.trash_generation("i1")

    assert [r["prompt_id"] for r in actions.rejected] == ["e1"]
    assert [r["prompt_id"] for batch in actions.deleted for r in batch] == ["i1"]


def test_favorite_slideshow_plays_favorite_items_and_folders_once(qtbot, monkeypatch):
    _resolve_by_id(monkeypatch)
    db = FakeDB([_image("i1", "a cat", 50, 1), _image("i2", "a dog", 50, 2)])
    db.set_generation_favorite("i2", True)  # a favorited item...
    view = GalleryView(db)
    qtbot.addWidget(view)
    view.refresh()
    lora = _at(_image_workflow(view._tree), 0, 0)  # "(no LoRA)"
    view._toggle_favorite(_key(_at(lora, 0)))   # ...and a favorited folder (the cat one)
    view._tree.setCurrentItem(_collection(view, FAVORITES_KEY))

    view._slideshows.start()

    qtbot.addWidget(view._slideshows.showing.shown)
    # The item, plus what the favorited folder's tile stands for.
    assert {item[2] for item in view._slideshows.showing._set.playlist._items} == {"i1", "i2"}
    view._slideshows.showing.close()


def test_enter_in_a_collection_slideshow_picks_the_slide_on_that_collection(qtbot, monkeypatch):
    _resolve_by_id(monkeypatch)
    view = GalleryView(FakeDB([_image("i1", "a cat", 50, 1), _image("i2", "a dog", 50, 2)]))
    qtbot.addWidget(view)
    view.refresh()
    view._tree.setCurrentItem(_collection(view, LATEST_KEY))
    view._slideshows.start()
    slideshow = view._slideshows.showing
    qtbot.addWidget(slideshow.shown)
    shown = slideshow._set.playlist.current()[2]

    slideshow.shown.keyPressEvent(QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Return, _NO_MOD))

    assert view._slideshows.showing is None               # out of the slideshow...
    assert view._tree.currentItem() is _collection(view, LATEST_KEY)  # ...still in the collection
    assert view._browser.selected_ids == {shown}     # with that image picked
    # And the item open in a tab: leaving a slideshow for an item is a decision to
    # work on it, which a folder under a stale form isn't.
    assert view._info_tabs.current_config_panel().displayed_row()["prompt_id"] == shown


def test_a_slideshow_ended_on_a_locked_slide_picks_that_slide_where_it_played(qtbot,
                                                                              monkeypatch):
    # Locking a slide is the user saying this is the one, so ending the slideshow there
    # picks it in the collection the slideshow was playing, the same as every other way out.
    _resolve_by_id(monkeypatch)
    view = GalleryView(FakeDB([_image("i1", "a cat", 50, 1), _image("i2", "a dog", 50, 2)]))
    qtbot.addWidget(view)
    view.refresh()
    view._tree.setCurrentItem(_alls(view._tree)["Latest"])
    view._slideshows.start()
    slideshow = view._slideshows.showing
    qtbot.addWidget(slideshow.shown)
    held = slideshow._set.playlist.current()[2]
    slideshow.shown.keyPressEvent(QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Down, _NO_MOD))

    slideshow.close()   # Escape, the spoken "close", a double-click: all this

    assert view._slideshows.showing is None
    assert held in view.listed_prompt_ids()       # its own folder in the pane...
    assert view._browser.selected_ids == {held}    # ...with it picked...
    assert view._info_tabs.current_config_panel().displayed_row()["prompt_id"] == held


def test_a_slideshow_ended_on_an_unlocked_slide_picks_that_slide_where_it_played(
        qtbot, monkeypatch):
    # However you leave -- Escape, a double-click, the spoken "close" -- the
    # image you were looking at is the one you want to find, picked in the collection
    # the slideshow was playing rather than left for you to hunt for.
    _resolve_by_id(monkeypatch)
    view = GalleryView(FakeDB([_image("i1", "a cat", 50, 1), _image("i2", "a dog", 50, 2)]))
    qtbot.addWidget(view)
    view.refresh()
    view._tree.setCurrentItem(_alls(view._tree)["Latest"])
    view._slideshows.start()
    slideshow = view._slideshows.showing
    qtbot.addWidget(slideshow.shown)
    shown = slideshow._set.playlist.current()[2]

    slideshow.close()

    assert view._tree.currentItem() is _alls(view._tree)["Latest"]
    assert view._browser.selected_ids == {shown}


def _laid_out_folder(qtbot, count=60):
    db = FakeDB([_image(f"i{n}", "a cat", 50, n) for n in range(1, count + 1)])
    view = GalleryView(db)
    _on_screen(qtbot, view, 1800, 1300)
    view._tree.setCurrentItem(view._leaf_by_id["i1"])
    qtbot.wait(1)
    return view, db


def test_a_slide_pages_down_latest_is_drawn_and_picked_on_leaving(qtbot, monkeypatch):
    # Latest draws fifty images at a time, so a slideshow stepped well past them hands
    # back one the collection has not drawn yet: it is drawn, picked and scrolled to,
    # rather than the collection coming back with nothing marked on it.
    _resolve_by_id(monkeypatch)
    view = GalleryView(FakeDB([_image(f"i{n}", f"scene {n}", 50, n)
                               for n in reversed(range(120))]))
    _on_screen(qtbot, view, 1800, 1300)
    view._tree.setCurrentItem(_alls(view._tree)["Latest"])
    view._slideshows.start()
    slideshow = view._slideshows.showing
    qtbot.addWidget(slideshow.shown)
    funestra_of(slideshow.shown)
    for _ in range(70):
        slideshow.slideshow_step(1)
        slideshow.tick()
    shown = slideshow._set.playlist.current()[2]
    assert shown not in _drawn(view)

    slideshow.close()
    qtbot.wait(1)

    assert view._browser.selected_ids == {shown}
    assert _in_view(view, shown)


def _folder_squares(view):
    return view._scroll.widget().findChildren(FolderTile)


def _folder_square_holding(view, prompt_id: str) -> str:
    """The key of the drawn square whose folder holds this image -- what the eye
    looks for when the pane lists folders rather than the images in them."""
    folder = gallery.settings_folder_key(view._db.get_generation(prompt_id),
                                         view.image_config_index())
    for tile in _folder_squares(view):
        if key_holds(tile.key, folder):
            return tile.key
    raise AssertionError(f"no drawn square holds {prompt_id} ({folder})")


def test_leaving_a_slideshow_of_all_picks_the_folder_square_its_slide_came_from(qtbot,
                                                                          monkeypatch):
    # All shows folders, not the images inside them, so there is no image to
    # pick -- the square the slide came out of is what the eye is looking for.
    _resolve_by_id(monkeypatch)
    view = GalleryView(FakeDB([_image("i1", "a cat", 50, 1), _image("i2", "a dog", 50, 2)]))
    qtbot.addWidget(view)
    view.refresh()
    all_row = _top_level(view._tree)["All"]
    view._tree.setCurrentItem(all_row)
    view._slideshows.start()
    slideshow = view._slideshows.showing
    qtbot.addWidget(slideshow.shown)
    shown = slideshow._set.playlist.current()[2]

    slideshow.close()

    assert view._tree.currentItem() is all_row
    assert view._browser.selected_ids == set()
    picked = [tile.key for tile in _folder_squares(view) if tile._selected]
    assert picked == [_folder_square_holding(view, shown)]


def test_leaving_a_favorites_slideshow_picks_the_favorited_folder_its_slide_came_from(
        qtbot, monkeypatch):
    # A star on a folder puts the folder in the Favorites collection, not the images
    # inside it, so a slide that came out of one has no image of its own there.
    _resolve_by_id(monkeypatch)
    view = GalleryView(FakeDB([_image("i1", "a cat", 50, 1), _image("i2", "a dog", 50, 2)]))
    _on_screen(qtbot, view, 1800, 1300)
    lora = _at(_image_workflow(view._tree), 0, 0)
    favorited = _key(_at(lora, 0))
    view._toggle_favorite(favorited)
    collection = _collection(view, FAVORITES_KEY)
    view._tree.setCurrentItem(collection)
    view._slideshows.start()
    slideshow = view._slideshows.showing
    qtbot.addWidget(slideshow.shown)
    shown = slideshow._set.playlist.current()[2]
    assert shown not in _drawn(view)

    slideshow.close()

    assert view._tree.currentItem() is collection
    picked = [tile.key for tile in _folder_squares(view) if tile._selected]
    assert picked == [favorited]


def test_the_image_a_locked_slideshow_ends_on_stays_picked_and_in_view_as_the_library_moves(
        qtbot, monkeypatch):
    _resolve_by_id(monkeypatch)
    view, db = _laid_out_folder(qtbot)
    far = view.listed_prompt_ids()[-3]
    _scroll_bar(view).setValue(_scroll_bar(view).maximum())  # draws the page it is on
    qtbot.wait(1)
    _click_tile(view, far)
    _scroll_bar(view).setValue(0)
    slideshow = _double_click_slideshow(view, qtbot)
    slideshow.shown.keyPressEvent(QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Down, _NO_MOD))
    slideshow.close()
    qtbot.wait(1)
    assert _in_view(view, far)

    db.add(_image("fresh", "a dog", 50, 999))
    view.refresh()
    qtbot.wait(1)

    assert view._browser._thumb_widgets[far]._selected
    assert _in_view(view, far)


def test_a_picked_image_holds_its_place_as_new_ones_land_above_it(qtbot):
    view, db = _laid_out_folder(qtbot)
    far = view.listed_prompt_ids()[-3]
    view._browser.reveal_tile(far)
    qtbot.wait(1)
    assert _in_view(view, far)

    for n in range(20):
        db.add(_image(f"n{n}", "a cat", 50, 500 + n))
    view.refresh()
    qtbot.wait(1)

    assert view.listed_prompt_ids().index(far) > 20
    assert _in_view(view, far)


def test_a_folder_read_from_its_top_shows_what_lands_there(qtbot):
    view, db = _laid_out_folder(qtbot)
    assert view.selected_prompt_ids() == [view.listed_prompt_ids()[0]]

    for n in range(20):
        db.add(_image(f"n{n}", "a cat", 50, 500 + n))
    view.refresh()
    qtbot.wait(1)

    assert _scroll_bar(view).value() == 0
    assert _in_view(view, "n19")


def test_taking_a_favorite_off_the_favorites_collection_leaves_it_where_it_was(qtbot):
    view = GalleryView(FakeDB([_image(f"i{n}", f"scene {n}", 50, n) | {"starred": 1}
                               for n in range(1, 61)]))
    _on_screen(qtbot, view, 1800, 1300)
    view._tree.setCurrentItem(_collection(view, FAVORITES_KEY))
    qtbot.wait(1)
    far = view.listed_prompt_ids()[-3]
    view._browser.reveal_tile(far)
    qtbot.wait(1)

    view.set_items_favorite([view.listed_prompt_ids()[0]], False)
    qtbot.wait(1)

    assert view._browser._thumb_widgets[far]._selected
    assert _in_view(view, far)


def test_reopening_a_slideshow_comes_back_to_the_slide_it_was_closed_on(qtbot, monkeypatch):
    # Closing a slideshow is usually a detour, not being done with it — so the next
    # one stands where the last was left rather than at the top of a fresh
    # shuffle, and the item you were looking at doesn't have to be found again.
    _resolve_by_id(monkeypatch)
    view = GalleryView(FakeDB([_image("i1", "a cat", 50, 1),
                               _image("i2", "a dog", 50, 2),
                               _image("i3", "a fox", 50, 3)]))
    qtbot.addWidget(view)
    view.refresh()
    _open_leaf(view)
    view._slideshows.start()
    first = view._slideshows.showing
    qtbot.addWidget(first.shown)
    first.shown.keyPressEvent(QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Right, _NO_MOD))
    stopped_on = first._set.playlist.current()[2]
    order = first._set.playlist.order_ids()
    first.close()

    view._slideshows.start()

    qtbot.addWidget(view._slideshows.showing.shown)
    assert view._slideshows.showing._set.playlist.current()[2] == stopped_on
    assert view._slideshows.showing._set.playlist.order_ids() == order   # the same pass, too
    view._slideshows.showing.close()


def test_a_slideshow_reopened_on_a_locked_slide_comes_back_locked(qtbot, monkeypatch):
    # A hold is the user saying this is the one: the slideshow reopened on the folder
    # it was playing is still stopped on that slide. A slideshow of Latest opens on the
    # newest image instead, which is what Latest is opened for.
    _resolve_by_id(monkeypatch)
    view = GalleryView(FakeDB([_image("i1", "a cat", 50, 1), _image("i2", "a dog", 50, 2)]))
    qtbot.addWidget(view)
    view.refresh()
    view._tree.setCurrentItem(view._leaf_by_id["i1"])
    view._slideshows.start()
    first = view._slideshows.showing
    qtbot.addWidget(first.shown)
    first.shown.keyPressEvent(QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Down, _NO_MOD))
    held = first._set.playlist.current()[2]
    first.close()

    view._slideshows.start()

    qtbot.addWidget(view._slideshows.showing.shown)
    assert view._slideshows.showing._set.playlist.current()[2] == held
    assert view._slideshows.showing.locked
    view._slideshows.showing.close()


def _resolve_each_to_its_own_kind(monkeypatch):
    """Resolve an image's preview to an image and a video's to a video, the way
    a slideshow of an image and the videos animated from it plays them."""
    monkeypatch.setattr(gallery, "resolve_preview", lambda row, places: (
        (f"{row['prompt_id']}.mp4", "video") if row["workflow_name"] == "wan22_i2v"
        else (f"{row['prompt_id']}.png", "image")))


def _animated_from(prompt_id, image, seed):
    """A video animated from *image*: a row down that image's column on the
    Nav Map."""
    return _row(prompt_id, "wan22_i2v",
                {"positive_prompt": "dance", "input_image": f"sdxl_t2i_{image}.png",
                 "seed": seed},
                f"wan22_i2v_{prompt_id}.mp4")


def _slideshow_of_the_folder_of(qtbot, monkeypatch, rows, image):
    """The Slideshow button pressed on the landscape folder holding *image*,
    the slideshow then stood on that image by its cell on the Nav Map."""
    _resolve_each_to_its_own_kind(monkeypatch)
    view = GalleryView(FakeDB(rows))
    qtbot.addWidget(view)
    _keys_are_the_gallerys(view)
    view.refresh()
    view._tree.setCurrentItem(view._leaf_by_id[image])
    view._bank.slideshow.click()
    slideshow = view._slideshows.showing
    qtbot.addWidget(slideshow.shown)
    funestra_of(slideshow.shown)
    slideshow.shown.press(f"{slideshow.shown.hud_side}_play_video|{image}.png")
    return view, slideshow


def _looping_actions_on_a_video(qtbot, monkeypatch, *, elsewhere=()):
    """A folder of two images, the first animated twice, looping that image's
    actions from the panel's loop button and standing on the first video."""
    view, slideshow = _slideshow_of_the_folder_of(
        qtbot, monkeypatch, [_image("p1", "a cat", 50, 1), _image("p2", "a cat", 50, 2),
                             _animated_from("v1", "p1", 1), _animated_from("v2", "p1", 2),
                             *elsewhere],
        "p1")
    slideshow.shown.press(f"{slideshow.shown.hud_side}_action_loop")
    slideshow.shown.press(f"{slideshow.shown.hud_side}_next")
    return view, slideshow


def _widened_onto_a_seed_from_another_folder(qtbot, monkeypatch):
    """A folder of two seeds of one image, its row widened by "more seeds" to an
    image of the next folder over, and standing on that one."""
    view, slideshow = _slideshow_of_the_folder_of(
        qtbot, monkeypatch, [_image("p1", "a cat", 50, 1), _image("p2", "a cat", 50, 2),
                             _image("p3", "a cat sitting", 50, 3)],
        "p1")
    slideshow.shown.press(f"{slideshow.shown.hud_side}_more_seeds")
    slideshow.shown.press(f"{slideshow.shown.hud_side}_next")
    slideshow.shown.press(f"{slideshow.shown.hud_side}_next")
    return view, slideshow


def _left_by_enter_then_the_slideshow_button(view, slideshow):
    _press_enter(slideshow)
    view._bank.slideshow.click()


def _minimized_then_the_slideshow_button(view, slideshow):
    slideshow.shown.showMinimized()
    view._bank.slideshow.click()


_LEFT_AND_COME_BACK_TO = pytest.mark.parametrize(
    "come_back",
    [_left_by_enter_then_the_slideshow_button, _minimized_then_the_slideshow_button],
    ids=["left_by_enter_then_slideshow_button", "minimized_then_slideshow_button"])


@_LEFT_AND_COME_BACK_TO
def test_a_slideshow_left_looping_actions_comes_back_looping_them_where_it_stood(
        qtbot, monkeypatch, come_back):
    # The Nav Map is part of where a slideshow was left: closed looping an image's
    # actions, the next one loops them again, standing where the last stood --
    # which in an action loop is one of the image's videos as often as not.
    view, slideshow = _looping_actions_on_a_video(qtbot, monkeypatch)
    looping, standing_on = slideshow.hud_map(), slideshow._set.playlist.current()
    assert (looping.loop, standing_on.prompt_id) == ("action", "v1")

    come_back(view, slideshow)

    reopened = view._slideshows.showing
    qtbot.addWidget(reopened.shown)
    assert reopened.hud_map() == looping
    assert reopened._set.playlist.current() == standing_on
    reopened.close()


@_LEFT_AND_COME_BACK_TO
def test_a_row_more_seeds_widened_comes_back_widened_where_it_stood(
        qtbot, monkeypatch, come_back):
    view, slideshow = _widened_onto_a_seed_from_another_folder(qtbot, monkeypatch)
    widened, standing_on = slideshow.hud_map(), slideshow._set.playlist.current()
    assert ([seed.prompt_id for seed in widened.seeds], standing_on.prompt_id) == (
        ["p2", "p3"], "p3")

    come_back(view, slideshow)

    reopened = view._slideshows.showing
    qtbot.addWidget(reopened.shown)
    assert reopened.hud_map() == widened
    assert reopened._set.playlist.current() == standing_on
    reopened.close()


def test_the_slideshow_button_on_another_folder_plays_that_folder_not_the_loop_left(
        qtbot, monkeypatch):
    view, slideshow = _looping_actions_on_a_video(
        qtbot, monkeypatch, elsewhere=[_image("q1", "a dog", 50, 3)])

    _press_enter(slideshow)
    view._tree.setCurrentItem(view._leaf_by_id["q1"])
    view._bank.slideshow.click()

    reopened = view._slideshows.showing
    qtbot.addWidget(reopened.shown)
    assert reopened._set.playlist.current().prompt_id == "q1"
    assert reopened.hud_map().loop == ""
    reopened.close()


def test_leaving_a_slideshow_on_a_slide_from_another_folder_opens_that_folder_on_it(
        qtbot, monkeypatch):
    # The Slideshow button plays the folder on screen, so leaving on one of the
    # image's videos has to put that video's own folder on screen, picked --
    # not the folder of the image the slideshow was started from.
    view, slideshow = _looping_actions_on_a_video(qtbot, monkeypatch)
    folder_of_the_video = oriented_key(gallery.settings_folder_key(
        view._db.get_generation("v1"), view.image_config_index()), LANDSCAPE)

    _press_enter(slideshow)

    assert view.selected_folder_key() == folder_of_the_video
    assert view._browser.selected_ids == {"v1"}


def test_giving_the_slideshows_back_as_the_window_closes_moves_the_gallery_nowhere(
        qtbot, monkeypatch):
    view, _slideshow = _looping_actions_on_a_video(qtbot, monkeypatch)
    folder_it_was_started_from = view.selected_folder_key()

    view.close_the_slideshows()

    assert view.selected_folder_key() == folder_it_was_started_from


def test_slideshow_items_carry_each_rows_thumbnail(qtbot, monkeypatch):
    # The neighbor stills either side of the shown item are drawn from these —
    # a video has no other still to show small.
    _resolve_by_id(monkeypatch)
    row = dict(_image("i1", "a cat", 50, 1), thumbnail_path="thumb.png")
    view = GalleryView(FakeDB([row]))
    qtbot.addWidget(view)
    view.refresh()

    assert view._slideshows.items_of([row])[0] == ("i1.png", "image", "i1", "thumb.png")


def test_favorite_slideshow_plays_a_favorite_item_in_a_favorite_folder_once(qtbot, monkeypatch):
    _resolve_by_id(monkeypatch)
    db = FakeDB([_image("i1", "a cat", 50, 1)])
    db.set_generation_favorite("i1", True)
    view = GalleryView(db)
    qtbot.addWidget(view)
    view.refresh()
    view._toggle_favorite(_select_first_leaf(view))  # star the folder holding it too
    view._tree.setCurrentItem(_collection(view, FAVORITES_KEY))

    view._slideshows.start()

    qtbot.addWidget(view._slideshows.showing.shown)
    assert [item[2] for item in view._slideshows.showing._set.playlist._items] == ["i1"]  # not twice
    view._slideshows.showing.close()


# --- a slideshow of a folder that is still filling ---------------------------


def _slideshow_of_first_leaf(qtbot, view):
    view.refresh()
    _select_first_leaf(view)
    view._slideshows.start()
    qtbot.addWidget(view._slideshows.showing.shown)
    funestra_of(view._slideshows.showing.shown)
    return view._slideshows.showing


def test_a_generation_that_lands_joins_the_open_slideshow(qtbot, monkeypatch):
    # Turning the slideshow on in a folder that is auto-generating and watching it
    # replay only what was there at the start is what sent people to double-click
    # the in-flight image instead.
    _resolve_by_id(monkeypatch)
    db = FakeDB([_image("i1", "a cat", 50, 1)])
    view = GalleryView(db)
    qtbot.addWidget(view)
    slideshow = _slideshow_of_first_leaf(qtbot, view)

    db.add(_image("i2", "a cat", 50, 2))              # Auto-Generate landed the next one
    view._on_reroll_finished("some-key", "i2")

    assert {item[2] for item in slideshow._set.playlist._items} == {"i1", "i2"}
    slideshow.close()


def test_a_generation_from_a_folder_the_slideshow_is_not_playing_stays_out(qtbot, monkeypatch):
    # Every completion is offered to the open slideshow; only the ones it would have
    # played had it opened now belong to it.
    _resolve_by_id(monkeypatch)
    db = FakeDB([_image("i1", "a cat", 50, 1)])
    view = GalleryView(db)
    qtbot.addWidget(view)
    slideshow = _slideshow_of_first_leaf(qtbot, view)

    db.add(_i2v_video("v1", "styleA"))                # another folder entirely
    view._on_reroll_finished("some-key", "v1")

    assert [item[2] for item in slideshow._set.playlist._items] == ["i1"]
    slideshow.close()


def _running(prompt_id, prompt="a cat", steps=50, seed=2):
    """A row for a generation still being made: same settings folder as an
    ``_image`` of the same prompt and steps, with no output file of its own."""
    return _row(prompt_id, "sdxl_t2i",
                {"positive_prompt": prompt, "steps": steps, "seed": seed}, "",
                status="running", output_files=json.dumps([]))


def _resolve_finished_only(monkeypatch):
    """Resolve a preview for finished rows only, as the real one does — a row
    still being made has no file to point at."""
    monkeypatch.setattr(
        gallery, "resolve_preview",
        lambda row, places: (None if row.get("status") != "completed"
                                 else (f"{row['prompt_id']}.png", "image")),
    )


def test_a_run_that_starts_to_look_like_something_joins_the_open_slideshow(qtbot, monkeypatch):
    # The wait is not worth a slide, but the first iterations coming in are the
    # best thing in a folder that is filling — and they used to reach the slideshow
    # only minutes later, as the finished file.
    _resolve_finished_only(monkeypatch)
    db = FakeDB([_image("i1", "a cat", 50, 1), _running("i2")])
    view = GalleryView(db)
    qtbot.addWidget(view)
    slideshow = _slideshow_of_first_leaf(qtbot, view)
    assert [item[2] for item in slideshow._set.playlist._items] == ["i1"]

    view._on_reroll_preview("some-key", "i2", b"a-frame")

    assert slideshow.holds("i2")
    assert ahead(slideshow._set.playlist, 1) == (b"a-frame", LIVE, "i2", None)
    slideshow.close()


def test_a_run_in_a_folder_the_slideshow_is_not_playing_stays_out(qtbot, monkeypatch):
    _resolve_finished_only(monkeypatch)
    db = FakeDB([_image("i1", "a cat", 50, 1),
                 _running("i2", prompt="a dog", steps=12)])   # another folder
    view = GalleryView(db)
    qtbot.addWidget(view)
    slideshow = _slideshow_of_first_leaf(qtbot, view)

    view._on_reroll_preview("some-key", "i2", b"a-frame")

    assert not slideshow.holds("i2")
    slideshow.close()


def test_a_run_being_made_joins_a_latest_slideshow_too(qtbot, monkeypatch):
    # Latest is a collection of results and a run has none yet, so it cannot answer
    # off its own list — but every generation this app makes lands there.
    _resolve_finished_only(monkeypatch)
    db = FakeDB([_image("i1", "a cat", 50, 1), _running("i2")])
    view = GalleryView(db)
    qtbot.addWidget(view)
    view.refresh()
    view._tree.setCurrentItem(_alls(view._tree)["Latest"])
    view._slideshows.start()
    qtbot.addWidget(view._slideshows.showing.shown)

    view._on_reroll_preview("some-key", "i2", b"a-frame")

    assert view._slideshows.showing.holds("i2")
    view._slideshows.showing.close()


def test_an_enhancement_being_made_is_nobody_slide(qtbot, monkeypatch):
    # It is a better version of an image the slideshow may already be playing, and it
    # says so in that image's own corner — not as a second, worse slide of it.
    _resolve_finished_only(monkeypatch)
    db = FakeDB([_image("i1", "a cat", 50, 1),
                 _row("e1", gallery.ENHANCE_WORKFLOW, {"seed": 1}, "",
                      status="running", output_files=json.dumps([]))])
    view = GalleryView(db)
    qtbot.addWidget(view)
    view.refresh()
    view._tree.setCurrentItem(_alls(view._tree)["Latest"])
    view._slideshows.start()
    qtbot.addWidget(view._slideshows.showing.shown)

    view._on_reroll_preview("some-key", "e1", b"a-frame")

    assert not view._slideshows.showing.holds("e1")
    view._slideshows.showing.close()


def test_a_run_the_slideshow_watched_becomes_the_file_it_lands_as(qtbot, monkeypatch):
    _resolve_finished_only(monkeypatch)
    db = FakeDB([_image("i1", "a cat", 50, 1), _running("i2")])
    view = GalleryView(db)
    qtbot.addWidget(view)
    slideshow = _slideshow_of_first_leaf(qtbot, view)
    view._on_reroll_preview("some-key", "i2", b"a-frame")

    db.get_generation("i2").update(_image("i2", "a cat", 50, 2))  # it finished
    view._on_reroll_finished("some-key", "i2")

    assert len(slideshow._set.playlist) == 2              # the same slide, finished
    assert ahead(slideshow._set.playlist, 1) == ("i2.png", "image", "i2", None)
    slideshow.close()


def test_a_run_on_screen_when_it_lands_stays_on_screen_as_its_file(qtbot, monkeypatch):
    _resolve_finished_only(monkeypatch)
    db = FakeDB([_image("i1", "a cat", 50, 1), _running("i2")])
    view = GalleryView(db)
    qtbot.addWidget(view)
    slideshow = _slideshow_of_first_leaf(qtbot, view)
    view._on_reroll_preview("some-key", "i2", b"a-frame")
    slideshow.slideshow_step(1)
    slideshow.tick()

    db.get_generation("i2").update(_image("i2", "a cat", 50, 2))
    view._on_reroll_finished("some-key", "i2")

    assert slideshow._set.playlist.current() == ("i2.png", "image", "i2", None)
    slideshow.close()


def test_a_run_that_stopped_being_made_leaves_the_open_slideshow(qtbot, monkeypatch):
    # Cancelled or failed: no file is coming, and the half-rendered frame it got
    # to would otherwise hold a place in the pass forever.
    _resolve_finished_only(monkeypatch)
    db = FakeDB([_image("i1", "a cat", 50, 1), _running("i2")])
    view = GalleryView(db)
    qtbot.addWidget(view)
    slideshow = _slideshow_of_first_leaf(qtbot, view)
    view._on_reroll_preview("some-key", "i2", b"a-frame")

    db.get_generation("i2")["status"] = "error"       # it is no longer in flight
    view._update_queue()

    assert not slideshow.holds("i2")
    slideshow.close()


def test_locking_a_slide_enhances_it_unless_one_is_already_in_flight(qtbot, tmp_path):
    db = _enhanceable_db(tmp_path, count=1)
    view = GalleryView(db, client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()

    assert view.enhance_from_slideshow("g0") is True
    (job,) = view._live_jobs.values()
    assert job.workflow.name == "image_enhance"

    # Asked again while that one is still in flight: nothing new is started.
    assert view.enhance_from_slideshow("g0") is False


def test_locking_a_slide_leaves_an_already_enhanced_image_alone(qtbot, tmp_path):
    # A hold is made with no view of the Enhance panel, so an image that already
    # carries an enhancement must not be re-derived at whatever the settings happen
    # to say now — however far those settings have moved since. Re-enhancing is
    # the thumbnail menu's job, pressed while looking at the settings it uses.
    db = _enhanceable_db(tmp_path, count=1)
    db.update_generation("g0", output_files=json.dumps([
        {"filename": "image_enhance_1.png", "subfolder": "image", "type": "output"},
        {"filename": "sdxl_t2i_g0.png", "subfolder": "image", "type": "output"},
    ]), original_files=json.dumps(
        [{"filename": "sdxl_t2i_g0.png", "subfolder": "image", "type": "output"}]))
    view = GalleryView(db, client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()
    _set_enhance(view, params={"enhance_steps": 41})  # nothing like what made it

    assert view.enhance_from_slideshow("g0") is False
    assert view._live_jobs == {}


def test_a_landed_enhancement_upgrades_that_item_in_the_open_slideshow(
        qtbot, tmp_path, monkeypatch):
    # The whole point of enhancing from a slideshow: what plays becomes the better
    # version. It lands minutes after the ask, by which time the slideshow is no longer
    # on the item that asked — it takes the upgrade wherever that item sits.
    paths = {"g0": "g0.png", "g1": "g1.png"}
    monkeypatch.setattr(gallery, "resolve_preview",
                        lambda row, places: (paths[row["prompt_id"]], "image"))
    db = _enhanceable_db(tmp_path, count=2)
    view = GalleryView(db, client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()
    _select_first_leaf(view)
    view._slideshows.start()
    qtbot.addWidget(view._slideshows.showing.shown)

    # The fold has happened: the row now leads with the enhanced file and wears
    # its thumbnail. That upgraded row is what reaches the slideshow.
    paths["g0"] = "g0_enhanced.png"
    db.update_generation("g0", thumbnail_path="g0_enhanced_thumb.png")
    view._slideshows.note_enhanced(db.get_generation("g0"))

    upgraded = ("g0_enhanced.png", "image", "g0", "g0_enhanced_thumb.png")
    assert upgraded in view._slideshows.showing._set.playlist._items
    view._slideshows.showing.close()


def test_a_slideshow_lock_on_a_video_asks_for_nothing(qtbot, tmp_path):
    db = _enhanceable_db(tmp_path, count=1)
    db.update_generation("g0", output_files=json.dumps(
        [{"filename": "clip.mp4", "subfolder": "video", "type": "output"}]))
    view = GalleryView(db, client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()
    assert view.enhance_from_slideshow("g0") is False


def test_a_slideshow_is_armed_with_each_images_versions(qtbot, tmp_path):
    db = _enhanceable_db(tmp_path, count=1)
    db.update_generation("g0", output_files=json.dumps([
        {"filename": "image_enhance_1.png", "subfolder": "image", "type": "output"},
        {"filename": "sdxl_t2i_g0.png", "subfolder": "image", "type": "output"},
    ]), original_files=json.dumps(
        [{"filename": "sdxl_t2i_g0.png", "subfolder": "image", "type": "output"}]))
    view = GalleryView(db, client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()
    _select_first_leaf(view)

    slideshow = _double_click_slideshow(view, qtbot)

    # Keyed by the file the folder shows the image under, which is not the one
    # the slideshow happens to have opened on, so the key comes from the same place
    # the slideshow's did — and asking the slideshow for it proves it took them.
    (key, computed), = view._slideshows.versions_of(
        [view.row_for(pid) for pid in view.listed_prompt_ids()]).items()
    levels = slideshow._levels.levels(base=key)
    assert levels == computed
    assert [version.path.name for version in levels] == \
        ["image_enhance_1.png", "sdxl_t2i_g0.png"]
    # Each carries its label, so the note can say which version is on screen.
    assert [version.label for version in levels] == ["Enhancement 1/1", "Original"]
    # And Down asks through the gallery, which holds the settings.
    assert slideshow._actions.enhance == view.enhance_from_slideshow
    slideshow.close()


def test_watching_a_generation_fullscreen_still_steps_its_folder(qtbot, monkeypatch):
    # A slideshow opened over something still being made has no place among the
    # folder's files — but the folder is still what it was opened from, so its
    # arrows step it rather than doing nothing at all.
    rows = [_image("i1", "a cat", 50, 1), _image("i2", "a cat", 50, 2)]
    view = GalleryView(FakeDB(rows))
    qtbot.addWidget(view)
    monkeypatch.setattr(
        gallery, "resolve_preview",
        lambda row, places: (f"{row['prompt_id']}.png", "image"),
    )
    view.refresh()
    _open_leaf(view)

    slideshow = _double_click_slideshow(view, qtbot, media=None)

    assert [item[2] for item in slideshow._set.playlist._items] == \
        view._browser.listed_prompt_ids()
    assert slideshow._set.playlist.index == 0
    slideshow.close()


def test_a_generation_still_in_flight_stays_out_of_a_slideshow(qtbot):
    # It used to be seeded with no file, and drew "Generating…" as its slide —
    # a blank between slides. It joins the slideshow when it has something to show.
    db = FakeDB([_running_row("in_flight", prompt="a cat")])
    view = GalleryView(db)
    qtbot.addWidget(view)
    view.refresh()

    assert view._slideshows.items_of(view._db.list_generations()) == []


def test_a_finished_generation_with_no_file_stays_out_of_a_slideshow(qtbot):
    db = FakeDB([_row("gone", "sdxl_t2i", {"positive_prompt": "a cat"}, "gone.png",
                      output_files="[]")])
    view = GalleryView(db)
    qtbot.addWidget(view)
    view.refresh()

    assert view._slideshows.items_of(view._db.list_generations()) == []


def test_a_folder_of_one_video_is_armed_like_any_other(qtbot, monkeypatch):
    # Most video folders here hold a single video, so skipping the arming for a
    # lone item is what made "fullscreen on a video" look like a different mode.
    rows = [_i2v_video("v1", "styleA")]
    view = GalleryView(FakeDB(rows))
    qtbot.addWidget(view)
    monkeypatch.setattr(
        gallery, "resolve_preview",
        lambda row, places: (f"{row['prompt_id']}.mp4", "video"),
    )
    view.refresh()
    view._tree.setCurrentItem(view._leaf_by_id["v1"])
    view._on_thumbnail_clicked("v1")

    slideshow = _double_click_slideshow(view, qtbot, media=("v1.mp4", "video"))

    assert slideshow._set.playlist._items == [("v1.mp4", "video", "v1", None)]
    assert slideshow._set.playlist.index == 0
    slideshow.close()

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from app_support.threading_utils import wait_until
from PySide6.QtCore import (
    QEvent,
    QPoint,
    Qt,
)
from PySide6.QtGui import (
    QKeyEvent,
)
from PySide6.QtWidgets import QApplication

from origenerator import (
    gallery,
    library_views,
)
from origenerator.fun_time_mode import Rect
from origenerator.gallery.collection import (
    ALL_ITEMS_KEY,
    ENHANCED_KEY,
    EXPERIMENTS_KEY,
    FAVORITES_KEY,
)
from origenerator.gallery.shapes import LANDSCAPE
from origenerator.gui import slideshow_director, two_screens
from origenerator.gui.gallery_view import GalleryView
from origenerator.gui.osr2_controls import Osr2Controls
from origenerator.gui.slideshow_hud import HudPlacement, slideshow_hud_model
from origenerator.item_shape import shaped_key
from origenerator.slideshow import LIVE
from origenerator.voice.app_commands import AppCommand
from origenerator.workflows.non_ai import non_ai_workflow
from tests.gallery_view_support import (
    _CTRL,
    _NO_MOD,
    _WAN_I2V,
    FakeActions,
    _a_slideshow_standing_on_its_own,
    _alls,
    _answer_menu,
    _at,
    _children_by_prompt,
    _collection,
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
    _open_all_items,
    _open_leaf,
    _pick_by_clicking,
    _press_enter,
    _reroll_client,
    _row,
    _running_row,
    _scroll_bar,
    _search_for,
    _seeded_db,
    _select_first_leaf,
    _set_enhance,
    _top_level,
)
from tests.his_monitors import HIS_TWO_MONITORS, PORTRAIT_MONITOR
from tests.marked_words import words
from tests.real_db import (
    database_of,
    keep_on_disk,
    keep_rows_on_disk,
    kept_file,
    kept_on_disk,
    put_rows,
)
from tests.slideshow_hud_support import (
    funestra_of,
    hud_button_names,
    hud_targets,
    press_key_on,
    program_of,
)
from tests.slideshow_support import ahead


def _minimized_from_the_taskbar(slideshow):
    program_of(slideshow).minimize()


def test_slideshow_opens_the_folders_media(qtbot, monkeypatch):
    keep_rows_on_disk(monkeypatch)
    view = GalleryView(database_of([_image("i1", "a cat", 50, 1), _image("i2", "a cat", 50, 2)]))
    qtbot.addWidget(view)
    view.refresh()
    _select_first_leaf(view)

    view.slideshows.start()

    assert len(view.slideshows.showing._set.playlist) == 2
    view.slideshows.showing.close()


def test_the_slideshow_begins_on_whichever_item_is_picked_in_the_folder(qtbot, monkeypatch):
    keep_rows_on_disk(monkeypatch)
    view = GalleryView(database_of([_image(f"i{n}", "a cat", 50, n) for n in (1, 2, 3)]))
    qtbot.addWidget(view)
    view.refresh()
    _open_leaf(view)

    for picked in view.listed_prompt_ids():
        view._gallery_pane.apply_selection(picked, _NO_MOD)
        view.slideshows.start()
        slideshow = view.slideshows.showing
        assert slideshow._set.playlist.current().prompt_id == picked
        slideshow.close()


def test_an_item_picked_while_a_slideshow_sits_minimized_is_where_the_button_begins_it(
        qtbot, monkeypatch):
    keep_rows_on_disk(monkeypatch)
    view = GalleryView(database_of([_image(f"i{n}", "a cat", 50, n) for n in (1, 2, 3)]))
    qtbot.addWidget(view)
    view.refresh()
    _open_leaf(view)
    view._buttons.slideshow.click()
    minimized = view.slideshows.showing
    _minimized_from_the_taskbar(minimized)
    picked = next(pid for pid in view.listed_prompt_ids()
                  if pid != minimized._set.playlist.current().prompt_id)
    view._gallery_pane.apply_selection(picked, _NO_MOD)

    view._buttons.slideshow.click()

    assert view.slideshows.showing._set.playlist.current().prompt_id == picked
    view.slideshows.showing.close()


def test_with_two_items_picked_the_slideshow_comes_back_to_where_the_last_one_closed(
        qtbot, monkeypatch):
    keep_rows_on_disk(monkeypatch)
    view = GalleryView(database_of([_image(f"i{n}", "a cat", 50, n) for n in (1, 2, 3)]))
    qtbot.addWidget(view)
    view.refresh()
    _open_leaf(view)
    view.slideshows.start()
    last = view.slideshows.showing
    closed_on = last._set.playlist.current().prompt_id
    last.close()
    elsewhere = [pid for pid in view.listed_prompt_ids() if pid != closed_on]
    view._gallery_pane.apply_selection(elsewhere[0], _NO_MOD)
    view._gallery_pane.apply_selection(elsewhere[1], _CTRL)

    view.slideshows.start()

    slideshow = view.slideshows.showing
    assert slideshow._set.playlist.current().prompt_id == closed_on
    slideshow.close()


def test_the_item_picked_comes_first_though_another_in_the_folder_is_being_enhanced(
        qtbot, monkeypatch):
    keep_rows_on_disk(monkeypatch)
    view = GalleryView(database_of([_image(f"i{n}", "a cat", 50, n) for n in (1, 2, 3)]))
    qtbot.addWidget(view)
    view.refresh()
    _open_leaf(view)
    view.slideshows.start()
    last = view.slideshows.showing
    last.close()
    (picked,) = view.selected_prompt_ids()
    enhancing = next(pid for pid in view.listed_prompt_ids() if pid != picked)
    view.slideshows.note_enhancing({enhancing: "running"})

    view.slideshows.start()

    slideshow = view.slideshows.showing
    assert slideshow._set.playlist.current().prompt_id == picked
    slideshow.close()


def _standalone_slideshow(qtbot, monkeypatch):
    keep_rows_on_disk(monkeypatch)
    view = GalleryView(database_of([_image("i1", "a cat", 50, 1), _image("i2", "a cat", 50, 2)]))
    qtbot.addWidget(view)
    view.refresh()
    _select_first_leaf(view)
    view.slideshows.start()
    funestra_of(view.slideshows.showing.shown)
    return view.slideshows.showing


def test_a_standalone_slideshow_wears_the_funestras_own_hud(qtbot, monkeypatch):
    slideshow = _standalone_slideshow(qtbot, monkeypatch)

    assert {"prev", "next", "lock", "trash"} <= set(hud_button_names(slideshow.shown))
    slideshow.close()


def test_minimize_this_funestra_on_a_standalone_hud_minimizes_the_slideshows_window(
        qtbot, monkeypatch):
    slideshow = _standalone_slideshow(qtbot, monkeypatch)
    assert "minimize" in hud_button_names(slideshow.shown)

    assert slideshow.shown.press(f"{slideshow.shown.hud_shape}_minimize")

    assert program_of(slideshow).window.minimized
    slideshow.close()


def test_a_standalone_huds_transport_lands_on_the_slideshow_itself(qtbot, monkeypatch):
    slideshow = _standalone_slideshow(qtbot, monkeypatch)
    shape = slideshow.shown.hud_shape
    opened = slideshow._set.playlist.current()

    slideshow.shown.press(f"{shape}_next")
    assert slideshow._set.playlist.current() != opened

    slideshow.shown.press(f"{shape}_lock")
    assert slideshow.locked is True
    slideshow.close()


def test_starting_a_slideshow_while_the_last_one_sits_minimized_puts_it_back_on_screen(
        qtbot, monkeypatch):
    view, slideshow = _a_slideshow_standing_on_its_own(qtbot, monkeypatch)
    view.resize(1200, 800)
    with qtbot.waitExposed(view):
        view.show()
    _minimized_from_the_taskbar(slideshow)
    assert program_of(slideshow).window.minimized

    view._buttons.slideshow.click()

    assert view.slideshows.showing is slideshow
    assert not program_of(slideshow).window.minimized
    slideshow.close()


def test_wasd_reach_a_standalone_slideshow_past_the_gallerys_own_key_filter(qtbot, monkeypatch):
    slideshow = _standalone_slideshow(qtbot, monkeypatch)
    opened = slideshow._set.playlist.current()

    press_key_on(slideshow, Qt.Key.Key_D)
    assert slideshow._set.playlist.current() != opened

    press_key_on(slideshow, Qt.Key.Key_A)
    assert slideshow._set.playlist.current() == opened
    slideshow.close()


def test_a_standalone_huds_order_pair_plays_the_library_of_its_shape(qtbot, monkeypatch):
    slideshow = _standalone_slideshow(qtbot, monkeypatch)
    played = []

    for order in ("latest", "shuffle"):
        slideshow.shown.press(f"{slideshow.shown.hud_shape}_{order}")
        playlist = slideshow._set.playlist
        played.append((slideshow.hud_order_label,
                       sorted(playlist.items[index][2] for index in playlist.order)))

    assert played == [("Latest", ["i1"]), ("Shuffle", ["i1", "i2"])]
    slideshow.close()


def _a_gallery_with_another_sites_picture(qtbot, monkeypatch):
    keep_rows_on_disk(monkeypatch)
    theirs = {**_row("o1", "outside picture:a-site", {"positive_prompt": "a cat", "seed": 2},
                     "a-site_o1.png"),
              "source": "outside", "workflow_version": "outside"}
    view = GalleryView(database_of([_image("i1", "a cat", 50, 1), theirs]))
    qtbot.addWidget(view)
    view.refresh()
    return view


def _stand_on_the_folder_of(view, prompt_id) -> None:
    folder = view.library.folder_key_of(view._db.get_generation(prompt_id))
    view._tree.setCurrentItem(view.toc.item_for(shaped_key(folder, LANDSCAPE)))


def _playing(slideshow) -> list[str]:
    playlist = slideshow._set.playlist
    return sorted(playlist.items[index][2] for index in playlist.order)


def test_a_standalone_huds_order_pair_leaves_out_what_other_sites_made(qtbot, monkeypatch):
    view = _a_gallery_with_another_sites_picture(qtbot, monkeypatch)
    _stand_on_the_folder_of(view, "i1")
    view.slideshows.start()
    slideshow = view.slideshows.showing
    funestra_of(slideshow.shown)
    played = []

    for order in ("latest", "shuffle"):
        slideshow.shown.press(f"{slideshow.shown.hud_shape}_{order}")
        played.append(_playing(slideshow))

    assert played == [["i1"], ["i1"]]
    slideshow.close()


def test_a_slideshow_started_on_latest_leaves_out_what_other_sites_made(qtbot, monkeypatch):
    view = _a_gallery_with_another_sites_picture(qtbot, monkeypatch)
    view._tree.setCurrentItem(_collection(view, ALL_ITEMS_KEY))

    view.slideshows.start()
    slideshow = view.slideshows.showing
    funestra_of(slideshow.shown)

    assert _playing(slideshow) == ["i1"]
    slideshow.close()


def test_a_slideshow_of_a_searchs_hits_plays_what_it_found(qtbot, monkeypatch):
    view = _a_gallery_with_another_sites_picture(qtbot, monkeypatch)
    view._tree.setCurrentItem(view.toc.item_for(shaped_key(gallery.ALL_KEY, LANDSCAPE)))
    _search_for(view, "cat")

    view.slideshows.start()
    slideshow = view.slideshows.showing
    funestra_of(slideshow.shown)

    assert _playing(slideshow) == ["i1", "o1"]
    slideshow.close()


def test_a_slideshow_of_a_searchs_hits_leaves_out_what_a_looping_workflow_made(
        qtbot, monkeypatch):
    keep_rows_on_disk(monkeypatch)
    looping = _row("l1", "wan22_flf2v_loop", {"positive_prompt": "a cat", "seed": 3}, "l1.mp4")
    view = GalleryView(database_of([_image("i1", "a cat", 50, 1), looping]))
    qtbot.addWidget(view)
    view.refresh()
    view._tree.setCurrentItem(view.toc.item_for(shaped_key(gallery.ALL_KEY, LANDSCAPE)))
    _search_for(view, "cat")

    view.slideshows.start()
    slideshow = view.slideshows.showing
    funestra_of(slideshow.shown)

    assert _playing(slideshow) == ["i1"]
    slideshow.close()


def test_a_slideshow_started_on_favorites_plays_what_other_sites_made_that_you_starred(
        qtbot, monkeypatch):
    keep_rows_on_disk(monkeypatch)
    theirs = {**_row("o1", "outside picture:a-site", {"positive_prompt": "a", "seed": 2},
                     "a-site_o1.png"),
              "source": "outside", "workflow_version": "outside", "starred": 1}
    view = GalleryView(database_of([{**_image("i1", "a cat", 50, 1), "starred": 1}, theirs]))
    qtbot.addWidget(view)
    view.refresh()
    view._tree.setCurrentItem(_collection(view, FAVORITES_KEY))

    view.slideshows.start()
    slideshow = view.slideshows.showing
    funestra_of(slideshow.shown)

    assert _playing(slideshow) == ["i1", "o1"]
    slideshow.close()


def test_a_slideshow_started_on_a_sites_folder_plays_what_it_holds(qtbot, monkeypatch):
    view = _a_gallery_with_another_sites_picture(qtbot, monkeypatch)
    _stand_on_the_folder_of(view, "o1")

    view.slideshows.start()
    slideshow = view.slideshows.showing
    funestra_of(slideshow.shown)

    assert _playing(slideshow) == ["o1"]
    slideshow.close()


def test_a_double_click_on_a_non_ai_video_starts_a_slideshow_on_it(qtbot, monkeypatch):
    keep_rows_on_disk(monkeypatch)
    non_ai ={**_row("n1", non_ai_workflow("sample full"), {"folder": "sample/full"},
                     "video one.mp4"),
              "source": "non_ai", "workflow_version": "non_ai"}
    view = GalleryView(database_of([_image("i1", "a cat", 50, 1), non_ai]))
    qtbot.addWidget(view)
    view.refresh()

    view._gallery_pane.slideshow_requested.emit("n1")
    slideshow = view.slideshows.showing
    funestra_of(slideshow.shown)

    assert slideshow._set.playlist.current()[2] == "n1"
    slideshow.close()


def test_a_video_asked_for_while_the_slideshow_plays_is_made(qtbot, monkeypatch, tmp_path):
    keep_rows_on_disk(monkeypatch)
    client = _reroll_client()
    db = _seeded_db(tmp_path)
    keep_on_disk(db)
    view = GalleryView(db, client=client)
    qtbot.addWidget(view)
    view.refresh()
    _select_first_leaf(view)
    view.slideshows.start()

    video = view._jobs.start_prepared("k", _WAN_I2V, _WAN_I2V.default_params())

    assert [call.args[1] for call in client.submit_job.call_args_list] == [video]


def test_locking_an_image_makes_its_waiting_enhancement_the_next_one_made(
        qtbot, tmp_path, monkeypatch):
    keep_rows_on_disk(monkeypatch)
    client = _reroll_client()
    db = _enhanceable_db(tmp_path, count=3)
    keep_on_disk(db)
    view = GalleryView(db, client=client)
    qtbot.addWidget(view)
    view.refresh()
    _select_first_leaf(view)
    view.slideshows.start()
    slideshow = view.slideshows.showing
    funestra_of(slideshow.shown)
    on_screen = slideshow.voice_target()
    view.enhance_items([on_screen, *({"g0", "g1", "g2"} - {on_screen})])

    slideshow.slideshow_toggle_lock()
    slideshow.tick()

    (wanted,) = view.enhance.jobs_targeting([view.row_for(on_screen)])
    assert view._jobs.queue_order[0] == wanted.prompt_id
    assert client.submit_job.call_args_list[-1].args[1] == wanted.prompt_id
    slideshow.close()


def test_the_slideshow_button_waits_until_there_is_something_to_play(qtbot):
    view = GalleryView(database_of([_running_row("in_flight", prompt="a cat")]))
    qtbot.addWidget(view)
    view.refresh()
    _select_first_leaf(view)

    assert view._buttons.slideshow.isHidden(), (
        "a button offering a slideshow that opens nothing is worse than no button, so it waits "
        "until there is something to play; only the Trash shows it, grayed, saying why")


def test_slideshow_button_follows_what_is_on_screen(qtbot, monkeypatch):
    keep_rows_on_disk(monkeypatch)
    db = database_of([_image("i1", "a cat", 50, 1)])
    db.set_generation_favorite("i1", True)
    view = GalleryView(db)
    qtbot.addWidget(view)
    view.refresh()
    _select_first_leaf(view)
    assert not view._buttons.slideshow.isHidden()
    assert "this folder" in view._buttons.slideshow.toolTip()

    view._tree.setCurrentItem(_collection(view, ALL_ITEMS_KEY))
    assert not view._buttons.slideshow.isHidden()
    assert "All" in view._buttons.slideshow.toolTip()
    view._tree.setCurrentItem(_collection(view, FAVORITES_KEY))
    assert not view._buttons.slideshow.isHidden()
    assert "Favorites" in view._buttons.slideshow.toolTip()

    view._tree.setCurrentItem(_collection(view, EXPERIMENTS_KEY))
    assert view._buttons.slideshow.isHidden()


def test_a_slideshow_after_one_of_the_favorites_collection_is_not_held_to_the_favorites(qtbot,
                                                                               monkeypatch):
    keep_rows_on_disk(monkeypatch)
    view = GalleryView(database_of([_image("i1", "a cat", 50, 1),
                               _row("i2", "sdxl_t2i",
                                    {"positive_prompt": "a cat", "steps": 50, "seed": 2},
                                    "sdxl_t2i_i2.png", starred=1)]))
    qtbot.addWidget(view)
    view.refresh()
    view._tree.setCurrentItem(_collection(view, FAVORITES_KEY))
    view.slideshows.start()
    assert view.slideshows.showing.hud_favorites_filter
    view.slideshows.showing.close()

    _select_first_leaf(view)
    view.slideshows.start()

    slideshow = view.slideshows.showing
    assert not slideshow.hud_favorites_filter
    assert sorted(item[2] for item in slideshow._set.playlist._items) == ["i1", "i2"]
    slideshow.close()


def test_a_slideshow_of_enhanced_lights_enhanced_only_and_the_next_slideshow_does_not(
        qtbot, monkeypatch):
    keep_rows_on_disk(monkeypatch)
    view = GalleryView(database_of([_image("i1", "a cat", 50, 1),
                               _enhanced_image("i2", "a cat", 50, 2)]))
    qtbot.addWidget(view)
    view.refresh()
    view._tree.setCurrentItem(_collection(view, ENHANCED_KEY))
    view.slideshows.start()
    assert view.slideshows.showing.hud_enhanced_filter
    view.slideshows.showing.close()

    _select_first_leaf(view)
    view.slideshows.start()

    slideshow = view.slideshows.showing
    assert not slideshow.hud_enhanced_filter
    assert sorted(item[2] for item in slideshow._set.playlist._items) == ["i1", "i2"]
    slideshow.close()


def test_favorites_begins_on_the_favorite_picked_there(qtbot, monkeypatch):
    keep_rows_on_disk(monkeypatch)
    view = GalleryView(database_of([
        _row(f"i{n}", "sdxl_t2i", {"positive_prompt": "a cat", "steps": 50, "seed": n},
             f"sdxl_t2i_i{n}.png", starred=1) for n in (1, 2, 3)]))
    qtbot.addWidget(view)
    view.refresh()
    view._tree.setCurrentItem(_collection(view, FAVORITES_KEY))
    view.slideshows.start()
    last = view.slideshows.showing
    closed_on = last._set.playlist.current().prompt_id
    last.close()
    picked = next(pid for pid in view.listed_prompt_ids() if pid != closed_on)
    view._gallery_pane.apply_selection(picked, _NO_MOD)

    view.slideshows.start()

    slideshow = view.slideshows.showing
    assert slideshow._set.playlist.current().prompt_id == picked
    assert slideshow.hud_favorites_filter
    slideshow.close()


def test_slideshow_plays_the_latest_collection(qtbot, monkeypatch):
    keep_rows_on_disk(monkeypatch)
    view = GalleryView(database_of([_image("i1", "a cat", 50, 1), _i2v_video("v1", "styleA")]))
    qtbot.addWidget(view)
    view.refresh()
    view._tree.setCurrentItem(_collection(view, ALL_ITEMS_KEY))

    view.slideshows.start()

    assert len(view.slideshows.showing._set.playlist) == 2
    view.slideshows.showing.close()


def test_a_slideshow_of_one_kinds_latest_plays_that_kind_alone(qtbot, monkeypatch):
    keep_rows_on_disk(monkeypatch)
    view = GalleryView(database_of([_image("i1", "a cat", 50, 1), _i2v_video("v1", "styleA")]))
    qtbot.addWidget(view)
    view.refresh()
    view._tree.setCurrentItem(_alls(view._tree)["Images"])

    view.slideshows.start()

    assert [item[2] for item in view.slideshows.showing._set.playlist._items] == ["i1"]
    view.slideshows.showing.close()


def test_latest_begins_on_its_newest_whatever_is_picked_there(qtbot, monkeypatch):
    keep_rows_on_disk(monkeypatch)
    view = GalleryView(database_of([_image("i1", "a cat", 50, 1), _image("i2", "a dog", 50, 2)]))
    qtbot.addWidget(view)
    view.refresh()
    _open_all_items(view)
    newest, older = view.listed_prompt_ids()
    view._gallery_pane.apply_selection(older, _NO_MOD)

    view.slideshows.start()

    slideshow = view.slideshows.showing
    assert slideshow._set.playlist.current().prompt_id == newest
    slideshow.close()


def test_the_enhanced_switch_narrows_a_slideshow_to_the_images_made_better(qtbot, monkeypatch):
    keep_rows_on_disk(monkeypatch)
    view = GalleryView(database_of([_image("i1", "a cat", 50, 1),
                               _enhanced_image("i2", "a dog", 50, 2)]))
    qtbot.addWidget(view)
    view.refresh()
    _open_all_items(view)
    view.slideshows.start()
    slideshow = view.slideshows.showing
    assert len(slideshow._set.playlist) == 2

    slideshow.set_enhanced_filter(True)

    assert [item[2] for item in slideshow._set.playlist._items] == ["i2"]
    slideshow.set_enhanced_filter(False)
    assert len(slideshow._set.playlist) == 2
    slideshow.close()


def test_a_standalone_huds_enhanceds_button_narrows_the_slideshow_to_the_enhanced(
        qtbot, monkeypatch):
    keep_rows_on_disk(monkeypatch)
    view = GalleryView(database_of([_image("i1", "a cat", 50, 1),
                               _enhanced_image("i2", "a dog", 50, 2)]))
    qtbot.addWidget(view)
    view.refresh()
    _open_all_items(view)
    view.slideshows.start()
    slideshow = view.slideshows.showing
    slideshow.shown.press(f"{slideshow.shown.hud_shape}_enhanced")

    assert slideshow.hud_enhanced_filter is True
    assert [item[2] for item in slideshow._set.playlist._items] == ["i2"]
    model = slideshow_hud_model(slideshow.shown.hud_shape, slideshow, HudPlacement(hosted=False))
    lit = {button.command: button.lit for row in model.rows for button in row}
    assert lit[f"{slideshow.shown.hud_shape}_enhanced"]
    assert "Enhanceds" in model.title
    slideshow.close()


def test_an_item_another_process_files_plays_next_on_a_slideshow_in_latest(qtbot, monkeypatch):
    keep_rows_on_disk(monkeypatch)
    db = database_of([_image("i1", "a cat", 50, 1), _image("i2", "a dog", 50, 2)])
    view = GalleryView(db)
    qtbot.addWidget(view)
    view.refresh()
    _open_all_items(view)
    view.slideshows.start()
    slideshow = view.slideshows.showing
    filed = _image("i3", "a bird", 50, 3)
    put_rows(db, [filed])

    view._poll()

    playlist = slideshow._set.playlist
    assert playlist.order_ids()[playlist.index + 1] == "i3"
    slideshow.close()


def test_an_item_evolver_upscales_plays_next_as_its_upscale_on_a_slideshow_in_latest(
        qtbot, monkeypatch):
    keep_rows_on_disk(monkeypatch)
    filed = {}
    monkeypatch.setattr(library_views.EvolverUpscales, "scan", lambda *args: SimpleNamespace(
        upscale_of=lambda video: filed.get(str(video))))
    db = database_of([_image("i1", "a cat", 50, 1), _image("i2", "a dog", 50, 2),
                 _image("i3", "a bird", 50, 3)])
    view = GalleryView(db)
    qtbot.addWidget(view)
    view.refresh()
    _open_all_items(view)
    view.slideshows.start()
    slideshow = view.slideshows.showing
    playlist = slideshow._set.playlist
    last = playlist.order_ids()[-1]
    filed[str(kept_file(f"sdxl_t2i_{last}.png"))] = f"{last}_topaz.mp4"
    db.set_evolver_upscale(last, f"{last}_topaz.mp4", None)

    view._poll()

    following = playlist.in_play_order()[playlist.index + 1]
    assert (following.prompt_id, str(following.path)) == (last, f"{last}_topaz.mp4")
    slideshow.close()


def test_a_generation_that_lands_unenhanced_stays_out_of_a_narrowed_slideshow(qtbot, monkeypatch):
    keep_rows_on_disk(monkeypatch)
    view = GalleryView(database_of([_enhanced_image("i2", "a cat", 50, 2)]))
    qtbot.addWidget(view)
    view.refresh()
    _open_all_items(view)
    view.slideshows.start()
    slideshow = view.slideshows.showing
    slideshow.set_enhanced_filter(True)
    put_rows(view._db, [_image("i3", "a cat", 50, 3), _enhanced_image("i4", "a cat", 50, 4)])
    view.refresh()
    plain, better = view._db.get_generation("i3"), view._db.get_generation("i4")
    monkeypatch.setattr(view.slideshows, "rows_at", lambda location: [plain, better])

    view.slideshows.note_finished(plain)
    view.slideshows.note_finished(better)

    assert sorted(item[2] for item in slideshow._set.playlist._items) == ["i2", "i4"]
    slideshow.set_enhanced_filter(False)
    assert sorted(item[2] for item in slideshow._set.playlist._items) == ["i2", "i3", "i4"]
    slideshow.close()


def test_clear_filter_leaves_f_mode_and_the_enhanced_filter_on(qtbot, monkeypatch):
    keep_rows_on_disk(monkeypatch)
    view = GalleryView(database_of([_image("i1", "a cat", 50, 1),
                               _row("i2", "sdxl_t2i",
                                    {"positive_prompt": "a dog", "steps": 50, "seed": 2,
                                     "enhance": True},
                                    "sdxl_t2i_i2.png", starred=1)]))
    qtbot.addWidget(view)
    view.refresh()
    _open_all_items(view)
    view.slideshows.start()
    slideshow = view.slideshows.showing
    slideshow.toggle_favorites_filter()
    slideshow.set_enhanced_filter(True)
    assert [item[2] for item in slideshow._set.playlist._items] == ["i2"]
    assert (slideshow.hud_favorites_filter, slideshow.hud_enhanced_filter) == (True, True)

    view._voice._run_app_command(AppCommand.FILTER_OFF)

    assert (slideshow.hud_favorites_filter, slideshow.hud_enhanced_filter) == (True, True)
    assert [item[2] for item in slideshow._set.playlist._items] == ["i2"]
    slideshow.close()


def test_filter_enhanced_turns_the_slideshows_switch_on_and_says_what_is_left(qtbot, monkeypatch):
    keep_rows_on_disk(monkeypatch)
    view = GalleryView(database_of([_image("i1", "a cat", 50, 1),
                               _enhanced_image("i2", "a dog", 50, 2)]))
    qtbot.addWidget(view)
    view.refresh()
    _open_all_items(view)
    view.slideshows.start()
    slideshow = view.slideshows.showing

    view._voice._run_app_command(AppCommand.ENHANCED_ON)

    assert slideshow.hud_enhanced_filter is True, (
        "a word that set some other filter would leave the HUD's button dark over a narrowed slideshow")
    assert "1 to play" in words(slideshow.shown._note)
    slideshow.close()


def test_clear_filter_said_over_the_enhanced_filter_says_the_action_filter_is_cleared(
        qtbot, monkeypatch):
    keep_rows_on_disk(monkeypatch)
    view = GalleryView(database_of([_image("i1", "a cat", 50, 1),
                               _enhanced_image("i2", "a dog", 50, 2)]))
    qtbot.addWidget(view)
    view.refresh()
    _open_all_items(view)
    view.slideshows.start()
    slideshow = view.slideshows.showing
    view._voice._run_app_command(AppCommand.ENHANCED_ON)

    view._voice._run_app_command(AppCommand.FILTER_OFF)

    assert slideshow.hud_enhanced_filter is True
    assert words(slideshow.shown._note) == "Filter: cleared (1)"
    slideshow.close()


def test_filter_enhanced_says_so_where_nothing_here_is_enhanced(qtbot, monkeypatch):
    keep_rows_on_disk(monkeypatch)
    view = GalleryView(database_of([_image("i1", "a cat", 50, 1)]))
    qtbot.addWidget(view)
    view.refresh()
    _open_all_items(view)
    view.slideshows.start()
    slideshow = view.slideshows.showing

    view._voice._run_app_command(AppCommand.ENHANCED_ON)

    assert slideshow.hud_enhanced_filter is False
    assert "nothing here is enhanced" in words(slideshow.shown._note)
    slideshow.close()


def test_filter_enhanced_with_no_slideshow_up_opens_none(qtbot, monkeypatch):
    keep_rows_on_disk(monkeypatch)
    view = GalleryView(database_of([_enhanced_image("i2", "a cat", 50, 2)]))
    qtbot.addWidget(view)
    view.refresh()
    _open_all_items(view)

    view._voice._run_app_command(AppCommand.ENHANCED_ON)

    assert not view._buttons.slideshow.isHidden()


def test_a_slideshow_wears_one_hud_and_leaves_the_osr2_to_core(qtbot, monkeypatch):
    slideshow = _standalone_slideshow(qtbot, monkeypatch)
    assert slideshow.findChildren(Osr2Controls) == [], (
        "a slideshow used to float two, the HUD and the OSR2 controls under it: between them "
        "the status was said twice and disagreed, and previous, next, lock and trash were drawn "
        "on both")
    posted = [button.command for _rect, button in hud_targets(slideshow).buttons]
    assert "robot_hand_cycle_shape" not in posted
    assert any(command.endswith("_clip_seconds_up") for command in posted)
    assert slideshow_hud_model(slideshow.shown.hud_shape, slideshow, HudPlacement(
        hosted=False, drives_the_osr2=True)).drive is None
    slideshow.close()


def _on_the_experiments_collection(qtbot, monkeypatch, db):
    keep_rows_on_disk(monkeypatch)
    keep_on_disk(db)
    view = GalleryView(db)
    qtbot.addWidget(view)
    view.refresh()
    view._tree.setCurrentItem(_collection(view, EXPERIMENTS_KEY))
    return view


def test_slideshow_plays_the_experiments_collection(qtbot, monkeypatch):
    view = _on_the_experiments_collection(qtbot, monkeypatch, database_of([
        _experiment_row("e1"),
        _experiment_row("e2", seed=10),
        _experiment_row("e3", verdict="up", seed=11),
    ]))
    assert not view._buttons.slideshow.isHidden(), (
        "going through a batch of experiments one at a time, full screen, is what a slideshow is for")
    assert "Experiments" in view._buttons.slideshow.toolTip()

    view.slideshows.start()

    assert {item[2] for item in view.slideshows.showing._set.playlist._items} == {"e1", "e2"}
    view.slideshows.showing.close()


def test_an_experiment_landing_is_lined_up_on_no_slideshow(qtbot, monkeypatch):
    db = database_of([_experiment_row("e1"), _experiment_row("e2", seed=10)])
    view = _on_the_experiments_collection(qtbot, monkeypatch, db)
    view.slideshows.start()

    put_rows(db, [_experiment_row("e3", seed=11)])
    view._on_reroll_finished("some-key", "e3")

    assert {item[2] for item in view.slideshows.showing._set.playlist._items} == {"e1", "e2"}, (
        "a background experiment that lands waits in the Experiments collection and moves "
        "nothing on screen, so no slideshow is fed it, the Experiments slideshow included")
    view.slideshows.showing.close()


def test_condemning_an_experiment_in_a_slideshow_rejects_it(qtbot):
    db = database_of([_experiment_row("e1"), _image("i1", "a cat", 50, 1)])
    actions = FakeActions()
    view = GalleryView(db, actions=actions)
    qtbot.addWidget(view)
    view.refresh()

    view.trash_generation("e1")
    view.trash_generation("i1")

    assert [r["prompt_id"] for r in actions.rejected] == ["e1"]
    assert [r["prompt_id"] for batch in actions.deleted for r in batch] == ["i1"]


def test_favorite_slideshow_plays_only_items_with_their_own_star(qtbot, monkeypatch):
    keep_rows_on_disk(monkeypatch)
    db = database_of([_image("i1", "a cat", 50, 1), _image("i2", "a dog", 50, 2),
                 _image("i3", "a dog", 50, 3)])
    db.set_generation_favorite("i2", True)
    view = GalleryView(db)
    qtbot.addWidget(view)
    view.refresh()
    lora = _at(_image_workflow(view._tree), 0, 0)
    db.set_folder_favorite(_key(_children_by_prompt(lora)["a cat"]), True, after_id=3)
    view.refresh()
    view._tree.setCurrentItem(_collection(view, FAVORITES_KEY))

    view.slideshows.start()

    assert [item[2] for item in view.slideshows.showing._set.playlist._items] == ["i2"]
    view.slideshows.showing.close()


def test_enter_in_a_collection_slideshow_picks_the_slide_on_that_collection(qtbot, monkeypatch):
    keep_rows_on_disk(monkeypatch)
    view = GalleryView(database_of([_image("i1", "a cat", 50, 1), _image("i2", "a dog", 50, 2)]))
    qtbot.addWidget(view)
    view.refresh()
    view._tree.setCurrentItem(_collection(view, ALL_ITEMS_KEY))
    view.slideshows.start()
    slideshow = view.slideshows.showing
    shown = slideshow._set.playlist.current()[2]

    press_key_on(slideshow, Qt.Key.Key_Return)

    assert view.slideshows.showing is None
    assert view._tree.currentItem() is _collection(view, ALL_ITEMS_KEY)
    assert view._gallery_pane.selected_ids == {shown}
    assert view.generate_pane.current_generate_tab().displayed_row()["prompt_id"] == shown, (
        "leaving a slideshow for an item is a decision to work on it")


def test_a_slideshow_ended_on_a_locked_slide_picks_that_slide_where_it_played(qtbot,
                                                                              monkeypatch):
    keep_rows_on_disk(monkeypatch)
    view = GalleryView(database_of([_image("i1", "a cat", 50, 1), _image("i2", "a dog", 50, 2)]))
    qtbot.addWidget(view)
    view.refresh()
    view._tree.setCurrentItem(_top_level(view._tree)["All"])
    view.slideshows.start()
    slideshow = view.slideshows.showing
    held = slideshow._set.playlist.current()[2]
    press_key_on(slideshow, Qt.Key.Key_Down)

    slideshow.close()

    assert view.slideshows.showing is None
    assert held in view.listed_prompt_ids()
    assert view._gallery_pane.selected_ids == {held}
    assert view.generate_pane.current_generate_tab().displayed_row()["prompt_id"] == held


def test_a_slideshow_ended_on_an_unlocked_slide_picks_that_slide_where_it_played(
        qtbot, monkeypatch):
    keep_rows_on_disk(monkeypatch)
    view = GalleryView(database_of([_image("i1", "a cat", 50, 1), _image("i2", "a dog", 50, 2)]))
    qtbot.addWidget(view)
    view.refresh()
    view._tree.setCurrentItem(_top_level(view._tree)["All"])
    view.slideshows.start()
    slideshow = view.slideshows.showing
    shown = slideshow._set.playlist.current()[2]

    slideshow.close()

    assert view._tree.currentItem() is _top_level(view._tree)["All"]
    assert view._gallery_pane.selected_ids == {shown}


def _laid_out_folder(qtbot, count=60):
    db = database_of([_image(f"i{n}", "a cat", 50, n) for n in range(1, count + 1)])
    view = GalleryView(db)
    _on_screen(qtbot, view, 1800, 1300)
    view._tree.setCurrentItem(view.toc.leaf_by_id["i1"])
    qtbot.wait(1)
    return view, db


def test_a_slide_pages_down_latest_is_drawn_and_picked_on_leaving(qtbot, monkeypatch):
    keep_rows_on_disk(monkeypatch)
    view = GalleryView(database_of([_image(f"i{n}", f"scene {n}", 50, n)
                               for n in reversed(range(120))]))
    _on_screen(qtbot, view, 1800, 1300)
    view._tree.setCurrentItem(_top_level(view._tree)["All"])
    view.slideshows.start()
    slideshow = view.slideshows.showing
    funestra_of(slideshow.shown)
    for _ in range(70):
        slideshow.slideshow_step(1)
        slideshow.tick()
    shown = slideshow._set.playlist.current()[2]
    assert shown not in _drawn(view)

    slideshow.close()
    qtbot.wait(1)

    assert view._gallery_pane.selected_ids == {shown}
    assert _in_view(view, shown)


def test_leaving_a_slideshow_of_all_picks_the_tile_of_the_item_it_ended_on(qtbot, monkeypatch):
    keep_rows_on_disk(monkeypatch)
    view = GalleryView(database_of([_image("i1", "a cat", 50, 1), _image("i2", "a dog", 50, 2)]))
    qtbot.addWidget(view)
    view.refresh()
    all_row = _top_level(view._tree)["All"]
    view._tree.setCurrentItem(all_row)
    view.slideshows.start()
    slideshow = view.slideshows.showing
    shown = slideshow._set.playlist.current()[2]

    slideshow.close()

    assert view._tree.currentItem() is all_row
    assert view._gallery_pane.selected_ids == {shown}


def test_the_image_a_locked_slideshow_ends_on_stays_picked_and_in_view_as_the_library_moves(
        qtbot, monkeypatch):
    keep_rows_on_disk(monkeypatch)
    view, db = _laid_out_folder(qtbot)
    far = view.listed_prompt_ids()[-3]

    def scroll_to_the_foot():
        QApplication.processEvents()
        _scroll_bar(view).setValue(_scroll_bar(view).maximum())
    wait_until(lambda: far in view._gallery_pane._thumb_widgets, pump=scroll_to_the_foot)
    _pick_by_clicking(view, far)
    _scroll_bar(view).setValue(0)
    slideshow = _double_click_slideshow(view, qtbot)
    press_key_on(slideshow, Qt.Key.Key_Down)
    slideshow.close()
    qtbot.wait(1)
    assert _in_view(view, far)

    put_rows(db, [_image("fresh", "a dog", 50, 999)])
    view.refresh()
    qtbot.wait(1)

    assert view._gallery_pane._thumb_widgets[far]._selected
    assert _in_view(view, far)


def test_a_picked_image_holds_its_place_as_new_ones_land_above_it(qtbot):
    view, db = _laid_out_folder(qtbot)
    far = view.listed_prompt_ids()[-3]
    view._gallery_pane.reveal_tile(far)
    qtbot.wait(1)
    assert _in_view(view, far)

    for n in range(20):
        put_rows(db, [_image(f"n{n}", "a cat", 50, 500 + n)])
    view.refresh()
    qtbot.wait(1)

    assert view.listed_prompt_ids().index(far) > 20
    assert _in_view(view, far)


def test_a_folder_read_from_its_top_shows_what_lands_there(qtbot):
    view, db = _laid_out_folder(qtbot)
    assert view.selected_prompt_ids() == [view.listed_prompt_ids()[0]]

    for n in range(20):
        put_rows(db, [_image(f"n{n}", "a cat", 50, 500 + n)])
    view.refresh()
    qtbot.wait(1)

    assert _scroll_bar(view).value() == 0
    assert _in_view(view, "n19")


def test_taking_a_favorite_off_the_favorites_collection_leaves_it_where_it_was(qtbot):
    view = GalleryView(database_of([_image(f"i{n}", f"scene {n}", 50, n) | {"starred": 1}
                               for n in range(1, 61)]))
    _on_screen(qtbot, view, 1800, 1300)
    view._tree.setCurrentItem(_collection(view, FAVORITES_KEY))
    qtbot.wait(1)
    far = view.listed_prompt_ids()[-3]
    view._gallery_pane.reveal_tile(far)
    qtbot.wait(1)

    view.set_items_favorite([view.listed_prompt_ids()[0]], False)
    qtbot.wait(1)

    assert view._gallery_pane._thumb_widgets[far]._selected
    assert _in_view(view, far)


def test_next_in_a_slideshow_of_a_folder_of_one_plays_on_through_the_library(qtbot, monkeypatch):
    keep_rows_on_disk(monkeypatch)
    view = GalleryView(database_of([_image("i1", "a cat", 50, 1),
                               _image("i2", "a dog", 50, 2),
                               _image("i3", "a fox", 50, 3)]))
    qtbot.addWidget(view)
    view.refresh()
    _open_leaf(view)
    view.slideshows.start()
    showing = view.slideshows.showing

    press_key_on(showing, Qt.Key.Key_Right)

    assert sorted(showing._set.playlist.order_ids()) == ["i1", "i2", "i3"]
    showing.close()


def test_next_in_a_slideshow_of_one_search_hit_plays_on_through_the_library(qtbot, monkeypatch):
    keep_rows_on_disk(monkeypatch)
    view = GalleryView(database_of([_image("i1", "a cat", 50, 1),
                               _image("i2", "a dog", 50, 2)]))
    qtbot.addWidget(view)
    view.refresh()
    _search_for(view, "cat")
    view.slideshows.start()
    showing = view.slideshows.showing

    press_key_on(showing, Qt.Key.Key_Right)

    assert sorted(showing._set.playlist.order_ids()) == ["i1", "i2"]
    showing.close()


def test_reopening_a_slideshow_comes_back_to_the_slide_it_was_closed_on(qtbot, monkeypatch):
    keep_rows_on_disk(monkeypatch)
    view = GalleryView(database_of([_image("i1", "a cat", 50, 1),
                               _image("i2", "a cat", 50, 2),
                               _image("i3", "a cat", 50, 3)]))
    qtbot.addWidget(view)
    view.refresh()
    _open_leaf(view)
    view.slideshows.start()
    first = view.slideshows.showing
    press_key_on(first, Qt.Key.Key_Right)
    stopped_on = first._set.playlist.current()[2]
    order = first._set.playlist.order_ids()
    first.close()

    view.slideshows.start()

    assert view.slideshows.showing._set.playlist.current()[2] == stopped_on, (
        "closing a slideshow is usually a detour, not being done with it")
    assert view.slideshows.showing._set.playlist.order_ids() == order
    view.slideshows.showing.close()


def test_a_slideshow_reopened_on_a_locked_slide_comes_back_locked(qtbot, monkeypatch):
    keep_rows_on_disk(monkeypatch)
    view = GalleryView(database_of([_image("i1", "a cat", 50, 1), _image("i2", "a dog", 50, 2)]))
    qtbot.addWidget(view)
    view.refresh()
    view._tree.setCurrentItem(view.toc.leaf_by_id["i1"])
    view.slideshows.start()
    first = view.slideshows.showing
    press_key_on(first, Qt.Key.Key_Down)
    held = first._set.playlist.current()[2]
    first.close()

    view.slideshows.start()

    assert view.slideshows.showing._set.playlist.current()[2] == held
    assert view.slideshows.showing.locked, (
        "a hold is the user saying this is the one, so the slideshow reopened on the folder it "
        "was playing is still stopped on that slide")
    view.slideshows.showing.close()


def _animated_from(prompt_id, image, seed):
    return _row(prompt_id, "wan22_i2v",
                {"positive_prompt": "dance", "input_image": f"sdxl_t2i_{image}.png",
                 "seed": seed},
                f"wan22_i2v_{prompt_id}.mp4")


def _slideshow_of_the_folder_of(qtbot, monkeypatch, rows, image):
    keep_rows_on_disk(monkeypatch)
    view = GalleryView(database_of(rows))
    qtbot.addWidget(view)
    _keys_are_the_gallerys(view)
    view.refresh()
    view._tree.setCurrentItem(view.toc.leaf_by_id[image])
    view._buttons.slideshow.click()
    slideshow = view.slideshows.showing
    funestra_of(slideshow.shown)
    slideshow.shown.press(
        f"{slideshow.shown.hud_shape}_play_video|{kept_file(f'sdxl_t2i_{image}.png')}")
    return view, slideshow


def _looping_actions_on_a_video(qtbot, monkeypatch, *, elsewhere=()):
    view, slideshow = _slideshow_of_the_folder_of(
        qtbot, monkeypatch, [_image("p1", "a cat", 50, 1), _image("p2", "a cat", 50, 2),
                             _animated_from("v1", "p1", 1), _animated_from("v2", "p1", 2),
                             *elsewhere],
        "p1")
    slideshow.shown.press(f"{slideshow.shown.hud_shape}_action_loop")
    slideshow.shown.press(f"{slideshow.shown.hud_shape}_next")
    return view, slideshow


def _widened_onto_a_seed_from_another_folder(qtbot, monkeypatch):
    view, slideshow = _slideshow_of_the_folder_of(
        qtbot, monkeypatch, [_image("p1", "a cat", 50, 1), _image("p2", "a cat", 50, 2),
                             _image("p3", "a cat sitting", 50, 3)],
        "p1")
    slideshow.shown.press(f"{slideshow.shown.hud_shape}_more_seeds")
    slideshow.shown.press(f"{slideshow.shown.hud_shape}_next")
    slideshow.shown.press(f"{slideshow.shown.hud_shape}_next")
    return view, slideshow


def _left_by_enter_then_the_slideshow_button(view, slideshow):
    _press_enter(slideshow)
    view._buttons.slideshow.click()


def _minimized_then_the_slideshow_button(view, slideshow):
    _minimized_from_the_taskbar(slideshow)
    view._buttons.slideshow.click()


_LEFT_AND_COME_BACK_TO = pytest.mark.parametrize(
    "come_back",
    [_left_by_enter_then_the_slideshow_button, _minimized_then_the_slideshow_button],
    ids=["left_by_enter_then_slideshow_button", "minimized_then_slideshow_button"])


@_LEFT_AND_COME_BACK_TO
def test_a_slideshow_left_looping_actions_comes_back_looping_them_where_it_stood(
        qtbot, monkeypatch, come_back):
    view, slideshow = _looping_actions_on_a_video(qtbot, monkeypatch)
    looping, standing_on = slideshow.hud_map(), slideshow._set.playlist.current()
    assert (looping.loop, standing_on.prompt_id) == ("action", "v1")

    come_back(view, slideshow)

    reopened = view.slideshows.showing
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

    reopened = view.slideshows.showing
    assert reopened.hud_map() == widened
    assert reopened._set.playlist.current() == standing_on
    reopened.close()


def test_the_slideshow_button_on_another_folder_plays_that_folder_not_the_loop_left(
        qtbot, monkeypatch):
    view, slideshow = _looping_actions_on_a_video(
        qtbot, monkeypatch, elsewhere=[_image("q1", "a dog", 50, 3)])

    _press_enter(slideshow)
    view._tree.setCurrentItem(view.toc.leaf_by_id["q1"])
    view._buttons.slideshow.click()

    reopened = view.slideshows.showing
    assert reopened._set.playlist.current().prompt_id == "q1"
    assert reopened.hud_map().loop == ""
    reopened.close()


def test_leaving_a_slideshow_on_a_slide_from_another_folder_opens_that_folder_on_it(
        qtbot, monkeypatch):
    view, slideshow = _looping_actions_on_a_video(qtbot, monkeypatch)
    folder_of_the_video = shaped_key(gallery.settings_folder_key(
        view._db.get_generation("v1"), view.library.reading.image_index), LANDSCAPE)

    _press_enter(slideshow)

    assert view.selected_folder_key() == folder_of_the_video, (
        "the Slideshow button plays the folder on screen, so leaving on one of the image's "
        "videos has to put that video's own folder on screen")
    assert view._gallery_pane.selected_ids == {"v1"}


def test_giving_the_slideshows_back_as_the_window_closes_moves_the_gallery_nowhere(
        qtbot, monkeypatch):
    view, _slideshow = _looping_actions_on_a_video(qtbot, monkeypatch)
    folder_it_was_started_from = view.selected_folder_key()

    view.close_the_slideshows()

    assert view.selected_folder_key() == folder_it_was_started_from


def test_slideshow_items_carry_each_rows_thumbnail(qtbot, monkeypatch):
    keep_rows_on_disk(monkeypatch)
    db = database_of([dict(_image("i1", "a cat", 50, 1), thumbnail_path="thumb.png")])
    view = GalleryView(db)
    qtbot.addWidget(view)
    view.refresh()

    assert view.slideshows.items_of([db.get_generation("i1")])[0] == (
        kept_file("sdxl_t2i_i1.png"), "image", "i1", "thumb.png")


def test_favorite_slideshow_plays_a_favorite_item_in_a_favorite_folder_once(qtbot, monkeypatch):
    keep_rows_on_disk(monkeypatch)
    db = database_of([_image("i1", "a cat", 50, 1)])
    db.set_generation_favorite("i1", True)
    view = GalleryView(db)
    qtbot.addWidget(view)
    view.refresh()
    view.toc_editing.toggle_favorite(_select_first_leaf(view))
    view._tree.setCurrentItem(_collection(view, FAVORITES_KEY))

    view.slideshows.start()

    assert [item[2] for item in view.slideshows.showing._set.playlist._items] == ["i1"]
    view.slideshows.showing.close()



def _slideshow_of_first_leaf(qtbot, view):
    view.refresh()
    _select_first_leaf(view)
    view.slideshows.start()
    funestra_of(view.slideshows.showing.shown)
    return view.slideshows.showing


def test_a_generation_that_lands_joins_the_open_slideshow(qtbot, monkeypatch):
    keep_rows_on_disk(monkeypatch)
    db = database_of([_image("i1", "a cat", 50, 1)])
    view = GalleryView(db)
    qtbot.addWidget(view)
    slideshow = _slideshow_of_first_leaf(qtbot, view)

    put_rows(db, [_image("i2", "a cat", 50, 2)])
    view._on_reroll_finished("some-key", "i2")

    assert {item[2] for item in slideshow._set.playlist._items} == {"i1", "i2"}, (
        "a slideshow in a folder that Populate is filling, replaying only what was there at the "
        "start, is what sent the user to double-click the image being made")
    slideshow.close()


def test_a_generation_that_lands_joins_a_slideshow_opened_from_a_double_clicked_tile(
        qtbot, monkeypatch):
    keep_rows_on_disk(monkeypatch)
    db = database_of([_image("i1", "a cat", 50, 1), _image("i2", "a cat", 50, 2)])
    view = GalleryView(db)
    qtbot.addWidget(view)
    view.refresh()
    _select_first_leaf(view)
    slideshow = view.slideshows.open_on_tile("i1")

    put_rows(db, [_image("i3", "a cat", 50, 3)])
    view._on_reroll_finished("some-key", "i3")

    assert "i3" in {item[2] for item in slideshow._set.playlist._items}
    slideshow.close()


def test_a_generation_from_a_folder_the_slideshow_is_not_playing_stays_out(qtbot, monkeypatch):
    keep_rows_on_disk(monkeypatch)
    db = database_of([_image("i1", "a cat", 50, 1)])
    view = GalleryView(db)
    qtbot.addWidget(view)
    slideshow = _slideshow_of_first_leaf(qtbot, view)

    put_rows(db, [_i2v_video("v1", "styleA")])
    view._on_reroll_finished("some-key", "v1")

    assert [item[2] for item in slideshow._set.playlist._items] == ["i1"]
    slideshow.close()


def _running(prompt_id, prompt="a cat", steps=50, seed=2):
    return _row(prompt_id, "sdxl_t2i",
                {"positive_prompt": prompt, "steps": steps, "seed": seed}, "",
                status="running", output_files=json.dumps([]))



def test_a_run_that_starts_to_look_like_something_joins_the_open_slideshow(qtbot, monkeypatch):
    keep_rows_on_disk(monkeypatch)
    db = database_of([_image("i1", "a cat", 50, 1), _running("i2")])
    view = GalleryView(db)
    qtbot.addWidget(view)
    slideshow = _slideshow_of_first_leaf(qtbot, view)
    assert [item[2] for item in slideshow._set.playlist._items] == ["i1"]

    view._on_reroll_preview("some-key", "i2", b"a-frame")

    assert slideshow.holds("i2"), (
        "the first frames coming in are the best thing in a folder that is filling, and they used "
        "to reach the slideshow only minutes later, as the finished file")
    assert ahead(slideshow._set.playlist, 1) == (b"a-frame", LIVE, "i2", None)
    slideshow.close()


def test_a_run_in_a_folder_the_slideshow_is_not_playing_stays_out(qtbot, monkeypatch):
    keep_rows_on_disk(monkeypatch)
    db = database_of([_image("i1", "a cat", 50, 1),
                 _running("i2", prompt="a dog", steps=12)])
    view = GalleryView(db)
    qtbot.addWidget(view)
    slideshow = _slideshow_of_first_leaf(qtbot, view)

    view._on_reroll_preview("some-key", "i2", b"a-frame")

    assert not slideshow.holds("i2")
    slideshow.close()


def test_a_run_being_made_joins_a_latest_slideshow_too(qtbot, monkeypatch):
    keep_rows_on_disk(monkeypatch)
    db = database_of([_image("i1", "a cat", 50, 1), _running("i2")])
    view = GalleryView(db)
    qtbot.addWidget(view)
    view.refresh()
    view._tree.setCurrentItem(_top_level(view._tree)["All"])
    view.slideshows.start()

    view._on_reroll_preview("some-key", "i2", b"a-frame")

    assert view.slideshows.showing.holds("i2")
    view.slideshows.showing.close()


def test_an_enhancement_being_made_is_nobody_slide(qtbot, monkeypatch):
    keep_rows_on_disk(monkeypatch)
    db = database_of([_image("i1", "a cat", 50, 1),
                 _row("e1", gallery.ENHANCE_WORKFLOW, {"seed": 1}, "",
                      status="running", output_files=json.dumps([]))])
    view = GalleryView(db)
    qtbot.addWidget(view)
    view.refresh()
    view._tree.setCurrentItem(_top_level(view._tree)["All"])
    view.slideshows.start()

    view._on_reroll_preview("some-key", "e1", b"a-frame")

    assert not view.slideshows.showing.holds("e1")
    view.slideshows.showing.close()


def _lands_as(db, row):
    db.update_generation(row["prompt_id"], status=row["status"])
    kept_on_disk(db, row, kept_file(json.loads(row["output_files"])[0]["filename"]))


def test_a_run_the_slideshow_watched_becomes_the_file_it_lands_as(qtbot, monkeypatch):
    keep_rows_on_disk(monkeypatch)
    db = database_of([_image("i1", "a cat", 50, 1), _running("i2")])
    view = GalleryView(db)
    qtbot.addWidget(view)
    slideshow = _slideshow_of_first_leaf(qtbot, view)
    view._on_reroll_preview("some-key", "i2", b"a-frame")

    _lands_as(db, _image("i2", "a cat", 50, 2))
    view._on_reroll_finished("some-key", "i2")

    assert len(slideshow._set.playlist) == 2
    assert ahead(slideshow._set.playlist, 1) == (kept_file("sdxl_t2i_i2.png"), "image", "i2", None)
    slideshow.close()


def test_a_run_on_screen_when_it_lands_stays_on_screen_as_its_file(qtbot, monkeypatch):
    keep_rows_on_disk(monkeypatch)
    db = database_of([_image("i1", "a cat", 50, 1), _running("i2")])
    view = GalleryView(db)
    qtbot.addWidget(view)
    slideshow = _slideshow_of_first_leaf(qtbot, view)
    view._on_reroll_preview("some-key", "i2", b"a-frame")
    slideshow.slideshow_step(1)
    slideshow.tick()

    _lands_as(db, _image("i2", "a cat", 50, 2))
    view._on_reroll_finished("some-key", "i2")

    assert slideshow._set.playlist.current() == (kept_file("sdxl_t2i_i2.png"), "image", "i2", None), (
        "the slideshow is told the run landed before the run leaves the in-flight list, which "
        "it would otherwise read as a run that stopped")
    slideshow.close()


def test_a_run_that_stopped_being_made_leaves_the_open_slideshow(qtbot, monkeypatch):
    keep_rows_on_disk(monkeypatch)
    db = database_of([_image("i1", "a cat", 50, 1), _running("i2")])
    view = GalleryView(db)
    qtbot.addWidget(view)
    slideshow = _slideshow_of_first_leaf(qtbot, view)
    view._on_reroll_preview("some-key", "i2", b"a-frame")

    db.update_generation("i2", status="error")
    view.job_queue.update()

    assert not slideshow.holds("i2")
    slideshow.close()


def test_locking_a_slide_enhances_it_unless_one_is_already_in_flight(qtbot, tmp_path):
    db = _enhanceable_db(tmp_path, count=1)
    view = GalleryView(db, client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()

    assert view.enhance.enhance_from_slideshow("g0") is True
    (job,) = view._live_jobs.values()
    assert job.workflow.name == "image_enhance"

    assert view.enhance.enhance_from_slideshow("g0") is False


def test_locking_a_slide_leaves_an_already_enhanced_image_alone(qtbot, tmp_path):
    db = _enhanceable_db(tmp_path, count=1)
    db.update_generation("g0", output_files=json.dumps([
        {"filename": "image_enhance_1.png", "subfolder": "image", "type": "output"},
        {"filename": "sdxl_t2i_g0.png", "subfolder": "image", "type": "output"},
    ]), original_files=json.dumps(
        [{"filename": "sdxl_t2i_g0.png", "subfolder": "image", "type": "output"}]))
    view = GalleryView(db, client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()
    _set_enhance(view, params={"enhance_steps": 41})

    assert view.enhance.enhance_from_slideshow("g0") is False, (
        "a lock is made with no view of the Enhance pane; enhancing again is the thumbnail menu's "
        "job, pressed while looking at the settings it uses")
    assert view._live_jobs == {}


def test_a_landed_enhancement_upgrades_that_item_in_the_open_slideshow(
        qtbot, tmp_path, monkeypatch):
    db = _enhanceable_db(tmp_path, count=2)
    keep_on_disk(db)
    view = GalleryView(db, client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()
    _select_first_leaf(view)
    view.slideshows.start()

    enhanced = tmp_path / "g0_enhanced.png"
    kept_on_disk(db, db.get_generation("g0"), enhanced)
    db.update_generation("g0", thumbnail_path="g0_enhanced_thumb.png")
    view.slideshows.note_enhanced(db.get_generation("g0"))

    upgraded = (enhanced, "image", "g0", "g0_enhanced_thumb.png")
    assert upgraded in view.slideshows.showing._set.playlist._items
    view.slideshows.showing.close()


def test_a_slideshow_lock_on_a_video_asks_for_nothing(qtbot, tmp_path):
    db = _enhanceable_db(tmp_path, count=1)
    db.update_generation("g0", output_files=json.dumps(
        [{"filename": "clip.mp4", "subfolder": "video", "type": "output"}]))
    view = GalleryView(db, client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()
    assert view.enhance.enhance_from_slideshow("g0") is False


def test_a_slideshow_is_armed_with_each_images_versions(qtbot, tmp_path, monkeypatch):
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

    (shown_under, computed), = view.slideshows.versions_of(
        [view.row_for(pid) for pid in view.listed_prompt_ids()]).items()
    versions = slideshow._versions[str(shown_under)]
    assert versions == computed
    assert [version.path.name for version in versions] == \
        ["image_enhance_1.png", "sdxl_t2i_g0.png"]
    assert [version.label for version in versions] == ["Enhancement 1/1", "Original"]
    pressed = []
    monkeypatch.setattr(view.enhance, "enhance_from_slideshow",
                        lambda prompt_id: pressed.append(prompt_id) or True)
    assert slideshow._actions.enhance("an-invented-id")
    assert pressed == ["an-invented-id"]
    slideshow.close()


def test_watching_a_generation_fullscreen_still_steps_its_folder(qtbot, monkeypatch):
    keep_rows_on_disk(monkeypatch)
    rows = [_image("i1", "a cat", 50, 1), _image("i2", "a cat", 50, 2)]
    view = GalleryView(database_of(rows))
    qtbot.addWidget(view)
    view.refresh()
    _open_leaf(view)

    slideshow = _double_click_slideshow(view, qtbot, media=None)

    assert [item[2] for item in slideshow._set.playlist._items] == \
        view._gallery_pane.listed_prompt_ids()
    assert slideshow._set.playlist.index == 0
    slideshow.close()


def test_a_generation_still_in_flight_stays_out_of_a_slideshow(qtbot):
    db = database_of([_running_row("in_flight", prompt="a cat")])
    view = GalleryView(db)
    qtbot.addWidget(view)
    view.refresh()

    assert view.slideshows.items_of(view._db.list_generations()) == []


def test_a_finished_generation_with_no_file_stays_out_of_a_slideshow(qtbot):
    db = database_of([_row("gone", "sdxl_t2i", {"positive_prompt": "a cat"}, "gone.png",
                      output_files="[]")])
    view = GalleryView(db)
    qtbot.addWidget(view)
    view.refresh()

    assert view.slideshows.items_of(view._db.list_generations()) == []


def test_a_folder_of_one_video_is_armed_like_any_other(qtbot, monkeypatch):
    keep_rows_on_disk(monkeypatch)
    rows = [_i2v_video("v1", "styleA")]
    view = GalleryView(database_of(rows))
    qtbot.addWidget(view)
    view.refresh()
    view._tree.setCurrentItem(view.toc.leaf_by_id["v1"])
    view._on_thumbnail_clicked("v1")

    video = kept_file("wan22_i2v_v1.mp4")
    slideshow = _double_click_slideshow(view, qtbot, media=(video, "video"))

    assert slideshow._set.playlist._items == [(video, "video", "v1", None)], (
        "most video folders hold a single video, so leaving a lone item out is what made fullscreen "
        "on a video look like a different mode")
    assert slideshow._set.playlist.index == 0
    slideshow.close()


def test_closing_the_gallery_closes_the_slideshow_up(qtbot, monkeypatch):
    keep_rows_on_disk(monkeypatch)
    view = GalleryView(database_of([_image("i1", "a cat", 50, 1)]))
    qtbot.addWidget(view)
    view.refresh()
    _select_first_leaf(view)
    view.slideshows.start()
    assert view.slideshows.showing is not None

    view.close()

    assert view.slideshows.showing is None


def test_once_core_is_up_on_two_monitors_the_folder_it_shows_plays_full_screen_on_the_other(
        qtbot, monkeypatch):
    monkeypatch.setattr(two_screens, "screens", lambda: HIS_TWO_MONITORS)
    keep_rows_on_disk(monkeypatch)
    view = GalleryView(database_of([_image("i1", "a cat", 50, 1), _image("i2", "a cat", 50, 2)]))
    qtbot.addWidget(view)
    view.refresh()
    _select_first_leaf(view)

    view._two_screens.core_is_up.emit()

    slideshow = view.slideshows.showing
    assert (len(slideshow._set.playlist), program_of(slideshow).place,
            program_of(slideshow).window.shown, view._two_screens.core_on()) == (
        2, Rect(*PORTRAIT_MONITOR.getRect()), True, "landscape")
    slideshow.close()


def test_a_slideshow_on_its_own_monitor_stays_on_top_until_an_omnipause(qtbot, monkeypatch):
    monkeypatch.setattr(two_screens, "screens", lambda: HIS_TWO_MONITORS)
    keep_rows_on_disk(monkeypatch)
    view = GalleryView(database_of([_image("i1", "a cat", 50, 1), _image("i2", "a cat", 50, 2)]))
    qtbot.addWidget(view)
    view.refresh()
    _select_first_leaf(view)
    view._two_screens.on_top.stand_alone(True)
    view._two_screens.core_is_up.emit()
    window = program_of(view.slideshows.showing).window
    on_top = window.on_top

    view.set_room_paused(True)

    assert (on_top, window.on_top) == (True, False)
    view.slideshows.showing.close()


def test_enter_in_a_slideshow_on_its_own_monitor_picks_its_item_in_core_and_plays_on(
        qtbot, monkeypatch):
    monkeypatch.setattr(two_screens, "screens", lambda: HIS_TWO_MONITORS)
    monkeypatch.setattr(slideshow_director, "bring_to_front", lambda window: None)
    keep_rows_on_disk(monkeypatch)
    view = GalleryView(database_of([_image("i1", "a cat", 50, 1), _image("i2", "a cat", 50, 2)]))
    qtbot.addWidget(view)
    view.refresh()
    _select_first_leaf(view)
    view._two_screens.core_is_up.emit()
    slideshow = view.slideshows.showing
    playing = slideshow._set.playlist.current().prompt_id

    press_key_on(slideshow, Qt.Key.Key_Return)

    assert (slideshow.is_showing(), view.selected_generation()) == (True, playing)
    slideshow.close()


def _core_beside_its_slideshow(qtbot, monkeypatch):
    monkeypatch.setattr(two_screens, "screens", lambda: HIS_TWO_MONITORS)
    keep_rows_on_disk(monkeypatch)
    view = GalleryView(database_of([_image(f"i{n}", "a cat", 50, n) for n in (1, 2, 3)]))
    qtbot.addWidget(view)
    view.refresh()
    _select_first_leaf(view)
    view.show()
    view._two_screens.core_is_up.emit()
    slideshow = view.slideshows.showing
    monkeypatch.setattr(view.keys, "other_window_owns_keys", lambda: False)
    steps = []
    monkeypatch.setattr(slideshow, "slideshow_step", steps.append)
    return view, slideshow, steps


def _arrow_pressed_in_core(view, key=Qt.Key.Key_Right) -> bool:
    return view.keys.eventFilter(view, QKeyEvent(QEvent.Type.KeyPress, key,
                                            Qt.KeyboardModifier.NoModifier))


def test_an_arrow_pressed_in_core_steps_the_slideshow_on_the_other_monitor(qtbot, monkeypatch):
    view, slideshow, steps = _core_beside_its_slideshow(qtbot, monkeypatch)

    taken = _arrow_pressed_in_core(view)

    assert (taken, steps) == (True, [1])
    slideshow.close()


@pytest.mark.parametrize(("key", "step"), [(Qt.Key.Key_D, 1), (Qt.Key.Key_A, -1)])
def test_the_letters_that_stand_for_arrows_step_the_slideshow_from_core_too(
        qtbot, monkeypatch, key, step):
    view, slideshow, steps = _core_beside_its_slideshow(qtbot, monkeypatch)

    taken = _arrow_pressed_in_core(view, key)

    assert (taken, steps) == (True, [step])
    slideshow.close()


def test_e_pressed_in_core_cycles_the_slideshows_loop(qtbot, monkeypatch):
    view, slideshow, _steps = _core_beside_its_slideshow(qtbot, monkeypatch)
    cycles = []
    monkeypatch.setattr(slideshow, "slideshow_loop_cycle", lambda: cycles.append(True))

    taken = _arrow_pressed_in_core(view, Qt.Key.Key_E)

    assert (taken, cycles) == (True, [True])
    slideshow.close()


def test_an_arrow_pressed_in_a_text_field_of_cores_stays_in_the_field(qtbot, monkeypatch):
    view, slideshow, steps = _core_beside_its_slideshow(qtbot, monkeypatch)
    view.activateWindow()
    view.search.field.setFocus()
    wait_until(lambda: QApplication.focusWidget() is view.search.field, pump=QApplication.processEvents)

    taken = _arrow_pressed_in_core(view)

    assert (taken, steps) == (False, [])
    slideshow.close()


def test_open_in_slideshow_on_an_items_menu_opens_the_slideshow_a_double_click_opens(
        qtbot, monkeypatch):
    keep_rows_on_disk(monkeypatch)
    view = GalleryView(database_of([_image("i1", "a cat", 50, 1), _image("i2", "a cat", 50, 2)]))
    qtbot.addWidget(view)
    view.refresh()
    _select_first_leaf(view)
    _answer_menu(monkeypatch, "Open in slideshow")

    view.generation_menu(["i2"], QPoint(0, 0))

    slideshow = view.slideshows.showing
    assert slideshow is not None
    assert slideshow.hud_prompt_id == "i2"
    slideshow.close()


def test_open_in_slideshow_on_picked_items_plays_those_items_alone(qtbot, monkeypatch):
    keep_rows_on_disk(monkeypatch)
    view = GalleryView(database_of([_image("i1", "a cat", 50, 1), _image("i2", "a cat", 50, 2),
                                    _image("i3", "a cat", 50, 3)]))
    qtbot.addWidget(view)
    view.refresh()
    _select_first_leaf(view)
    _answer_menu(monkeypatch, "Open in slideshow")

    view.generation_menu(["i1", "i3"], QPoint(0, 0))

    slideshow = view.slideshows.showing
    assert slideshow is not None
    assert {item[2] for item in slideshow._set.playlist._items} == {"i1", "i3"}
    slideshow.close()

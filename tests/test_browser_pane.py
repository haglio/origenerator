"""The browser pane, constructed alone — no GalleryView anywhere in sight.

Until the coupling inversion this file could not exist: BrowserPane took the
whole view and reached into it 93 times, so its 668 statements were exercised
only from inside tests/test_gallery_view.py. Now it takes six narrow
collaborators, and the stubs below are the whole of what standing one up
costs. The wider behavior — how the view answers the pane's signals — stays
pinned where the view is built; what lives here is the pane's own promise:
its selection model, its collections, and what each collection gathers.

Fixture values are fabricated throughout (see CLAUDE.md).
"""
from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from PyQt6 import sip
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QLabel, QWidget

from origenerator import gallery
from origenerator.gallery.collection import (
    ENHANCED_KEY,
    EXPERIMENTS_KEY,
    FAVORITES_KEY,
    RECENTS_KEY,
    REQUESTS_KEY,
    TRASH_KEY,
    FolderCollection,
)
from origenerator.gallery.sides import LANDSCAPE
from origenerator.gui import browser_pane
from origenerator.gui.browser_pane import (
    BrowserPane,
    BrowserScrollArea,
    LeadTiles,
    PaneHost,
    TreeNavigation,
)
from origenerator.gui.folder_tile import FolderTile
from origenerator.gui.thumbnail_widget import ThumbnailWidget
from origenerator.orientation import oriented_key

_NO_MOD = Qt.KeyboardModifier.NoModifier
_CTRL = Qt.KeyboardModifier.ControlModifier
_SHIFT = Qt.KeyboardModifier.ShiftModifier


def _row(prompt_id, seed, created_at=None):
    """One finished, fabricated image row — the least a collection tile needs."""
    return {
        "prompt_id": prompt_id,
        "workflow_name": "sdxl_t2i",
        "positive_prompt": "scene one",
        "seed": seed,
        "params_json": json.dumps({"positive_prompt": "scene one", "seed": seed}),
        "status": "completed",
        "output_files": json.dumps([{"filename": f"{prompt_id}.png",
                                     "subfolder": ""}]),
        "thumbnail_path": None,
        "starred": 0,
        "created_at": created_at,
    }


def _ago(**elapsed):
    return (datetime.now(UTC) - timedelta(**elapsed)).strftime("%Y-%m-%d %H:%M:%S")


class _StubDB:
    """Answers the four questions the pane asks a database, from a list."""

    def __init__(self, rows=()):
        self.rows = list(rows)

    def list_generations(self):
        return list(self.rows)

    def list_requests(self):
        return []

    def get_generation(self, prompt_id):
        return next((r for r in self.rows if r["prompt_id"] == prompt_id), None)

    def recent_durations(self, workflow_name):
        return []


class _StubJobQueue:
    def __init__(self, order=(), leading=None):
        self.jobs_by_folder = {}
        self.queue_order = list(order)
        self.training = None
        self._leading = leading

    def job_for(self, key):
        return None if self._leading is None else SimpleNamespace(prompt_id=self._leading)

    def shield(self, prompt_id, shielded):
        pass


class _StubAuto:
    def is_active(self, key):
        return False


def _pane(qtbot, rows=(), lead_tiles=lambda group: LeadTiles(), scroll=None, jobs=None,
          selected=None):
    if scroll is None:
        scroll = BrowserScrollArea()
        qtbot.addWidget(scroll)
    pane = BrowserPane(
        scroll, _StubDB(rows), jobs or _StubJobQueue(), _StubAuto(),
        TreeNavigation(
            selected_folder_key=lambda: selected,
            folder_context=lambda key: "",
            group_for_key=lambda key: None,
        ),
        PaneHost(
            image_rows=list,
            animated_preview=lambda row: None,
            enhancing_run=lambda row: None,
            enhance_settings=lambda: gallery.EnhanceSettings(),
            experiments_enabled=lambda: False,
            lead_tiles=lead_tiles,
            item_name=lambda prompt_id: f"item {prompt_id}",
        ),
    )
    return pane, scroll


def _open_recents(pane, rows):
    pane.set_model(rows, {}, [], [], [])
    pane.show_collection(RECENTS_KEY)


def _shown_in_order(scroll):
    layout = scroll.widget().layout()
    return [_named(layout.itemAt(index).widget()) for index in range(layout.count())]


def _named(widget):
    if isinstance(widget, ThumbnailWidget):
        return widget.prompt_id
    if isinstance(widget, QLabel):
        return widget.text()
    return type(widget).__name__


def test_the_pane_stands_alone_on_six_stubs(qtbot):
    pane, scroll = _pane(qtbot)
    pane.show_empty()
    assert scroll.widget() is not None       # the pane filled its own canvas
    assert pane.listed_prompt_ids() == []


def test_a_tile_is_captioned_with_the_name_the_gallery_gives_its_item(qtbot):
    pane, _scroll = _pane(qtbot)

    _open_recents(pane, [_row("g1", 1)])

    assert pane._thumb_widgets["g1"]._text_label.text() == "item g1"


def test_the_second_look_for_a_place_goes_with_the_canvas_it_was_for(qtbot):
    holder = QWidget()
    qtbot.addWidget(holder)
    pane, scroll = _pane(qtbot, scroll=BrowserScrollArea(holder))
    pane.show_empty()
    pane.return_to(pane.place())

    sip.delete(scroll)

    qtbot.wait(10)


def test_a_plain_click_picks_one_tile_and_ctrl_toggles_another(qtbot):
    rows = [_row("g1", 1), _row("g2", 2), _row("g3", 3)]
    pane, _scroll = _pane(qtbot, rows)
    _open_recents(pane, rows)

    pane.apply_selection("g1", _NO_MOD)
    assert pane.selected_prompt_ids() == ["g1"]

    pane.apply_selection("g3", _CTRL)
    assert pane.selected_prompt_ids() == ["g1", "g3"]

    pane.apply_selection("g1", _CTRL)          # toggles it back off
    assert pane.selected_prompt_ids() == ["g3"]


def test_a_tile_click_picks_by_the_keys_held_during_that_click(qtbot):
    rows = [_row("g1", 1), _row("g2", 2)]
    pane, _scroll = _pane(qtbot, rows)
    _open_recents(pane, rows)
    elsewhere = QWidget()
    qtbot.addWidget(elsewhere)
    qtbot.keyClick(elsewhere, Qt.Key.Key_Z, _CTRL)  # Qt Test leaves Ctrl down app-wide

    pane._thumb_widgets["g1"].clicked.emit("g1", _NO_MOD)
    pane._thumb_widgets["g2"].clicked.emit("g2", _NO_MOD)

    assert pane.selected_prompt_ids() == ["g2"]


def test_shift_extends_a_contiguous_run_from_the_anchor(qtbot):
    rows = [_row(f"g{n}", n) for n in range(1, 6)]
    pane, _scroll = _pane(qtbot, rows)
    _open_recents(pane, rows)

    pane.apply_selection("g2", _NO_MOD)
    pane.apply_selection("g4", _SHIFT)

    assert pane.selected_prompt_ids() == ["g2", "g3", "g4"]


def test_clearing_the_thumbnail_selection_announces_it(qtbot):
    rows = [_row("g1", 1)]
    pane, _scroll = _pane(qtbot, rows)
    _open_recents(pane, rows)
    pane.apply_selection("g1", _NO_MOD)
    heard = []
    pane.selection_changed.connect(lambda: heard.append(True))

    pane.clear_thumbnail_selection()

    assert pane.selected_prompt_ids() == []
    assert heard  # the view re-aims its buttons off exactly this


def _sixty():
    return [_row(f"g{n}", n) for n in range(1, 61)]


def _drawn(scroll, kind=ThumbnailWidget):
    return list(scroll.widget().findChildren(kind))


def test_recents_draws_a_page_at_a_time_of_everything_it_lists(qtbot):
    rows = _sixty()
    pane, scroll = _pane(qtbot, rows)
    _open_recents(pane, rows)

    assert [tile.prompt_id for tile in _drawn(scroll)] == [f"g{n}" for n in range(1, 51)]
    assert pane.listed_prompt_ids() == [row["prompt_id"] for row in rows]


def test_a_settings_folder_draws_a_page_at_a_time_of_everything_it_lists(qtbot):
    rows = _sixty()
    pane, scroll = _pane(qtbot, rows)

    pane.show_thumbnails(gallery.SettingsGroup(key="k1", label="scene one", rows=rows))

    assert len(_drawn(scroll)) == browser_pane._PAGE
    assert pane.listed_prompt_ids() == [row["prompt_id"] for row in rows]


def test_favorites_draws_a_page_at_a_time_of_everything_it_lists(qtbot):
    rows = [dict(row, starred=1) for row in _sixty()]
    pane, scroll = _pane(qtbot, rows)
    pane.set_model(rows, {LANDSCAPE: gallery.build_gallery_tree(rows)}, rows, [], [])

    pane.show_collection(FAVORITES_KEY, LANDSCAPE)

    assert len(_drawn(scroll)) == browser_pane._PAGE
    assert len(pane.listed_prompt_ids()) == 60


def test_the_trash_draws_a_page_at_a_time_of_everything_it_lists(qtbot):
    held = _sixty()
    pane, scroll = _pane(qtbot)
    pane.set_model([], {}, [], [], held)

    pane.show_collection(TRASH_KEY)

    assert len(_drawn(scroll)) == browser_pane._PAGE
    assert len(pane.listed_prompt_ids()) == 60


def test_the_experiments_draw_a_page_at_a_time_of_everything_they_list(qtbot):
    rows = _sixty()
    pane, scroll = _pane(qtbot, rows)
    pane.set_model([], {}, [], rows, [])

    pane.show_collection(EXPERIMENTS_KEY)

    assert len(_drawn(scroll)) == browser_pane._PAGE
    assert len(pane.listed_prompt_ids()) == 60


def test_the_requests_draw_a_page_at_a_time_of_everything_they_list(qtbot):
    rows = _sixty()
    pane, scroll = _pane(qtbot, rows)
    pane.set_model([], {}, [], [], [], request_items=[{"row": row} for row in rows])

    pane.show_collection(REQUESTS_KEY)

    assert len(_drawn(scroll)) == browser_pane._PAGE
    assert len(pane.listed_prompt_ids()) == 60


def test_a_folder_of_your_own_draws_a_page_at_a_time_of_everything_it_lists(qtbot):
    rows = _sixty()
    pane, scroll = _pane(qtbot, rows)

    pane.show_custom_folder(gallery.CustomGroup(key="custom:1", label="mine", children=[],
                                                rows=rows, folder_id=1))

    assert len(_drawn(scroll)) == browser_pane._PAGE
    assert len(pane.listed_prompt_ids()) == 60


def test_a_folder_of_folders_draws_a_page_of_them_at_a_time(qtbot):
    folders = [gallery.SettingsGroup(key=f"k{n}", label=f"scene {n}", rows=[_row(f"g{n}", n)])
               for n in range(60)]
    pane, scroll = _pane(qtbot)

    pane.show_folder_tiles(folders)

    assert len(_drawn(scroll, FolderTile)) == browser_pane._PAGE


def test_a_page_too_short_to_fill_the_pane_draws_on_until_the_pane_is_full(qtbot):
    rows = [_row(f"g{n}", n) for n in range(300)]
    pane, scroll = _pane(qtbot, rows)
    scroll.resize(1900, 2400)
    scroll.show()
    qtbot.waitExposed(scroll)

    pane.show_thumbnails(gallery.SettingsGroup(key="k1", label="scene one", rows=rows))

    drawn_to = scroll.widget().heightForWidth(scroll.viewport().width())
    assert drawn_to >= scroll.viewport().height() + browser_pane._REACH
    assert len(_drawn(scroll)) < len(rows)


def test_scrolling_to_the_foot_of_a_pane_draws_on_by_a_page_not_to_the_end(qtbot):
    rows = [_row(f"g{n}", n) for n in range(300)]
    pane, scroll = _pane(qtbot, rows)
    scroll.setWidgetResizable(True)
    scroll.resize(1900, 1000)
    scroll.show()
    qtbot.waitExposed(scroll)
    pane.show_thumbnails(gallery.SettingsGroup(key="k1", label="scene one", rows=rows))
    opened_on = len(_drawn(scroll))
    qtbot.wait(1)

    scroll.verticalScrollBar().setValue(scroll.verticalScrollBar().maximum())

    assert opened_on < len(_drawn(scroll)) < len(rows)


def test_revealing_a_folder_past_the_first_page_draws_its_square(qtbot):
    folders = [gallery.SettingsGroup(key=f"k{n}", label=f"scene {n}", rows=[_row(f"g{n}", n)])
               for n in range(60)]
    pane, scroll = _pane(qtbot)
    pane.show_folder_tiles(folders)

    assert pane.reveal_folder("k59")
    assert [tile.key for tile in _drawn(scroll, FolderTile) if tile._selected] == ["k59"]


def test_revealing_a_picture_past_the_first_page_draws_and_picks_its_tile(qtbot):
    rows = _sixty()
    pane, scroll = _pane(qtbot, rows)
    pane.show_thumbnails(gallery.SettingsGroup(key="k1", label="scene one", rows=rows))

    assert pane.reveal_tile("g60")
    assert pane.selected_prompt_ids() == ["g60"]
    assert "g60" in [tile.prompt_id for tile in _drawn(scroll)]


def test_latest_heads_each_batch_with_when_it_was_made(qtbot):
    rows = [_row("g1", 1, "2026-09-12 23:00:00"), _row("g2", 2, "2026-09-12 22:50:00"),
            _row("g3", 3, "2026-09-12 19:00:00")]
    pane, scroll = _pane(qtbot, rows)
    _open_recents(pane, rows)

    first, _, second = gallery.section_headings(rows)
    assert _shown_in_order(scroll) == [first, "g1", "g2", second, "g3"]


def _running(prompt_id, seed, created_at=None):
    """A fabricated run still going: no file of its own yet."""
    return dict(_row(prompt_id, seed, created_at), status="running",
                output_files=json.dumps([]))


def test_latest_opens_on_its_first_heading_with_the_work_still_running_beneath_it(qtbot):
    finished = [_row("g1", 1, _ago(minutes=5))]
    pane, scroll = _pane(qtbot, [_running("j1", 2), *finished])
    _open_recents(pane, finished)

    [heading] = gallery.section_headings(finished)
    assert _shown_in_order(scroll) == [heading, "InFlightCard", "g1"]


def _waiting(prompt_id, seed, created_at=None):
    """A fabricated run still in this app's line."""
    return dict(_running(prompt_id, seed, created_at), status="pending")


def test_latest_draws_the_back_of_the_line_first_and_the_run_being_made_last(qtbot):
    # Latest reads newest first, and the run being made is the next to land, so
    # its card stands beside the newest finished item, where it will go; the
    # last run in the line stands farthest from it.
    finished = [_row("g1", 1, _ago(minutes=5))]
    rows = [_running("j1", 2), _waiting("j2", 3), _waiting("j3", 4), *finished]
    pane, _scroll = _pane(qtbot, rows, jobs=_StubJobQueue(order=["j1", "j2", "j3"]))

    _open_recents(pane, finished)

    assert list(pane._inflight_cards) == ["j3", "j2", "j1"]


def test_latest_redraws_its_cards_when_the_line_changes_order(qtbot):
    # A drag in the queue, or a run ComfyUI turns out to be making, moves runs
    # without adding or taking away any.
    jobs = _StubJobQueue(order=["j1", "j2"])
    pane, _scroll = _pane(qtbot, [_waiting("j1", 1), _waiting("j2", 2)], jobs=jobs,
                          selected=RECENTS_KEY)
    _open_recents(pane, [])
    jobs.queue_order = ["j2", "j1"]

    pane.refresh_inflight()

    assert list(pane._inflight_cards) == ["j1", "j2"]


def test_latest_puts_work_started_long_after_the_newest_picture_in_a_now_section(qtbot):
    finished = [_row("g1", 1, _ago(hours=5))]
    pane, scroll = _pane(qtbot, [_running("j1", 2), *finished])
    _open_recents(pane, finished)

    [heading] = gallery.section_headings(finished)
    assert _shown_in_order(scroll) == ["Now", "InFlightCard", heading, "g1"]


def test_a_later_page_of_latest_heads_only_the_batches_that_begin_on_it(qtbot):
    later = [_row(f"a{n}", n, f"2026-09-12 22:{59 - n:02d}:00") for n in range(55)]
    earlier = [_row(f"b{n}", n, f"2026-09-12 18:{59 - n:02d}:00") for n in range(5)]
    rows = later + earlier
    pane, scroll = _pane(qtbot, rows)
    _open_recents(pane, rows)

    pane._pages.draw(50)

    first, second = [heading for heading in gallery.section_headings(rows) if heading]
    shown = _shown_in_order(scroll)
    assert shown[0] == first
    assert shown[shown.index("a50") - 1] == "a49"   # the batch carries on over the page
    assert shown[shown.index("b0") - 1] == second


def test_a_folders_grid_heads_its_batches_with_when_they_were_made(qtbot):
    rows = [_row("g1", 1, "2026-09-12 23:00:00"), _row("g2", 2, "2026-09-12 19:00:00")]
    pane, scroll = _pane(qtbot, rows)

    pane.show_thumbnails(gallery.SettingsGroup(key="k1", label="scene one", rows=rows))

    first, second = gallery.section_headings(rows)
    assert _shown_in_order(scroll) == [first, "g1", second, "g2"]


def test_a_video_tile_finds_its_start_frame_in_the_models_picture_index(qtbot):
    picture = _row("img", 1)
    video = {**_row("vid", 2), "workflow_name": "wan22_i2v",
             "params_json": json.dumps({"input_image": "img.png [output]", "noise_seed": 2}),
             "output_files": json.dumps([{"filename": "vid.mp4", "subfolder": ""}])}
    pane, _scroll = _pane(qtbot, [picture, video])
    pane.set_model([], {}, [], [], [], image_index=gallery.build_image_config_index([picture]))

    pane.show_thumbnails(gallery.SettingsGroup(key="k1", label="scene one", rows=[video]))

    assert [b.toolTip() for b in pane._thumb_widgets["vid"]._corner_buttons] == [
        "Randomize video seed", "Randomize image seed"]


def test_a_folder_last_made_a_long_while_ago_gives_its_new_tile_a_section_of_its_own(qtbot):
    rows = [_row("g1", 1, _ago(hours=5))]
    pane, scroll = _pane(qtbot, rows, lead_tiles=lambda group: LeadTiles(reroll=QLabel("new")))

    pane.show_thumbnails(gallery.SettingsGroup(key="k1", label="scene one", rows=rows))

    [heading] = gallery.section_headings(rows)
    assert _shown_in_order(scroll) == ["Now", "new", heading, "g1"]


def test_a_folder_made_lately_keeps_its_new_tile_in_the_newest_section(qtbot):
    rows = [_row("g1", 1, _ago(minutes=5))]
    pane, scroll = _pane(qtbot, rows, lead_tiles=lambda group: LeadTiles(reroll=QLabel("new")))

    pane.show_thumbnails(gallery.SettingsGroup(key="k1", label="scene one", rows=rows))

    [heading] = gallery.section_headings(rows)
    assert _shown_in_order(scroll) == [heading, "new", "g1"]


def test_the_request_tile_stands_above_a_folders_sections_when_it_has_several(qtbot):
    rows = [_row("g1", 1, _ago(minutes=5)), _row("g2", 2, _ago(hours=5))]
    tiles = LeadTiles(reroll=QLabel("new"), request=QLabel("request"))
    pane, scroll = _pane(qtbot, rows, lead_tiles=lambda group: tiles)

    pane.show_thumbnails(gallery.SettingsGroup(key="k1", label="scene one", rows=rows))

    first, second = gallery.section_headings(rows)
    assert _shown_in_order(scroll) == ["request", first, "new", "g1", second, "g2"]


def test_a_now_section_counts_toward_putting_the_request_tile_above_the_sections(qtbot):
    rows = [_row("g1", 1, _ago(hours=5))]
    tiles = LeadTiles(reroll=QLabel("new"), request=QLabel("request"))
    pane, scroll = _pane(qtbot, rows, lead_tiles=lambda group: tiles)

    pane.show_thumbnails(gallery.SettingsGroup(key="k1", label="scene one", rows=rows))

    [heading] = gallery.section_headings(rows)
    assert _shown_in_order(scroll) == ["request", "Now", "new", heading, "g1"]


def test_the_request_tile_stays_with_a_folders_only_section(qtbot):
    rows = [_row("g1", 1, _ago(minutes=5))]
    tiles = LeadTiles(reroll=QLabel("new"), request=QLabel("request"))
    pane, scroll = _pane(qtbot, rows, lead_tiles=lambda group: tiles)

    pane.show_thumbnails(gallery.SettingsGroup(key="k1", label="scene one", rows=rows))

    [heading] = gallery.section_headings(rows)
    assert _shown_in_order(scroll) == [heading, "new", "request", "g1"]


def test_the_run_in_front_stands_after_the_request_tile_where_its_picture_will_land(qtbot):
    rows = [_row("g1", 1, _ago(minutes=5))]
    tiles = LeadTiles(reroll=QLabel("new"), request=QLabel("request"),
                      generating=QLabel("generating"))
    pane, scroll = _pane(qtbot, rows, lead_tiles=lambda group: tiles)

    pane.show_thumbnails(gallery.SettingsGroup(key="k1", label="scene one", rows=rows))

    [heading] = gallery.section_headings(rows)
    assert _shown_in_order(scroll) == [heading, "new", "request", "generating", "g1"]


def test_the_run_in_front_stays_beside_the_plus_when_the_request_tile_stands_above(qtbot):
    rows = [_row("g1", 1, _ago(minutes=5)), _row("g2", 2, _ago(hours=5))]
    tiles = LeadTiles(reroll=QLabel("new"), request=QLabel("request"),
                      generating=QLabel("generating"))
    pane, scroll = _pane(qtbot, rows, lead_tiles=lambda group: tiles)

    pane.show_thumbnails(gallery.SettingsGroup(key="k1", label="scene one", rows=rows))

    first, second = gallery.section_headings(rows)
    assert _shown_in_order(scroll) == ["request", first, "new", "generating", "g1",
                                       second, "g2"]


def test_a_folder_draws_its_runs_back_of_the_line_first_and_the_one_in_front_last(qtbot):
    # The run in front lands next, beside the newest picture, so the runs
    # waiting after it stand before it rather than between it and that picture.
    finished = _row("g1", 1, _ago(minutes=5))
    rows = [_running("r1", 2), _waiting("r2", 3), _waiting("r3", 4), finished]
    tiles = LeadTiles(reroll=QLabel("new"), generating=QLabel("generating"))
    pane, scroll = _pane(qtbot, rows, lead_tiles=lambda group: tiles,
                         jobs=_StubJobQueue(order=["r1", "r2", "r3"], leading="r1"))

    pane.show_thumbnails(gallery.SettingsGroup(key="k1", label="scene one", rows=rows))

    [heading] = gallery.section_headings([finished])
    assert _shown_in_order(scroll) == [heading, "new", "InFlightCard", "InFlightCard",
                                       "generating", "g1"]
    assert list(pane._inflight_cards) == ["r3", "r2"]


def test_work_running_in_a_folder_made_a_long_while_ago_goes_in_the_now_section(qtbot):
    running = _running("r1", 2, _ago(minutes=1))
    finished = _row("g1", 1, _ago(hours=5))
    pane, scroll = _pane(qtbot, [running, finished])

    pane.show_thumbnails(gallery.SettingsGroup(key="k1", label="scene one",
                                               rows=[running, finished]))

    [heading] = gallery.section_headings([finished])
    assert _shown_in_order(scroll) == ["Now", "InFlightCard", heading, "g1"]


def test_the_experiments_collection_heads_each_batch_it_collected(qtbot):
    rows = [_row("e1", 1, "2026-09-12 23:00:00"), _row("e2", 2, "2026-09-12 19:00:00")]
    pane, scroll = _pane(qtbot, rows)
    pane.set_model([], {}, [], rows, [])

    pane.show_collection(EXPERIMENTS_KEY)

    first, second = gallery.section_headings(rows)
    assert _shown_in_order(scroll) == [first, "e1", second, "e2"]


def test_the_requests_collection_heads_each_batch_of_what_was_asked_for(qtbot):
    rows = [_row("r1", 1, "2026-09-12 23:00:00"), _row("r2", 2, "2026-09-12 19:00:00")]
    pane, scroll = _pane(qtbot, rows)
    pane.set_model([], {}, [], [], [], request_items=[{"row": row} for row in rows])

    pane.show_collection(REQUESTS_KEY)

    first, second = gallery.section_headings(rows)
    assert _shown_in_order(scroll) == [first, "r1", second, "r2"]


def test_rows_for_collection_answers_by_name_not_by_what_is_on_screen(qtbot):
    recents = [_row("g1", 1)]
    held = [_row("d1", 9)]
    pane, _scroll = _pane(qtbot, recents)
    pane.set_model(recents, {}, [], [], held)
    pane.show_collection(RECENTS_KEY)

    assert [r["prompt_id"] for r in pane.rows_for_collection(TRASH_KEY)] == ["d1"]


@pytest.mark.parametrize("folder, kind", [
    (gallery.ALL_KEY, "generations"), ("image", "images"), ("video/wan22_i2v", "videos")])
def test_an_empty_latest_names_the_kind_its_folder_holds(qtbot, folder, kind):
    pane, scroll = _pane(qtbot)
    pane.set_model([], {}, [], [], [])

    pane.show_collection(FolderCollection(RECENTS_KEY, folder).key, LANDSCAPE)

    assert scroll.widget().text().startswith(f"No recent {kind} yet.")


def test_the_empty_trash_hint_promises_no_expiry(qtbot):
    pane, _scroll = _pane(qtbot)
    pane.set_model([], {}, [], [], [])
    hint = pane._trash_empty_hint()

    assert "as long as you leave them" in hint
    assert "day" not in hint   # no window to count, so no number to state


def _made_with(prompt_id, checkpoint, prompt="scene one", starred=0):
    row = _row(prompt_id, 1)
    row["params_json"] = json.dumps({"positive_prompt": prompt, "seed": 1,
                                     "checkpoint": checkpoint})
    row["starred"] = starred
    return row


def _models(tree):
    (images,) = tree
    (workflow,) = gallery.child_groups(images)
    return {model.label: model for model in gallery.child_groups(workflow)}


def test_a_folders_latest_lists_only_what_that_folder_holds(qtbot):
    rows = [_made_with("a1", "alpha.safetensors"), _made_with("b1", "beta.safetensors")]
    tree = gallery.build_gallery_tree(rows)
    pane, _scroll = _pane(qtbot, rows)
    pane.set_model(rows, {LANDSCAPE: tree}, rows, [], [])

    pane.show_collection(FolderCollection(RECENTS_KEY, _models(tree)["alpha"].key).key, LANDSCAPE)

    assert pane.listed_prompt_ids() == ["a1"]


def test_a_folders_trash_holds_what_was_deleted_from_that_folder(qtbot):
    kept = [_made_with("a1", "alpha.safetensors"), _made_with("b1", "beta.safetensors")]
    deleted = [_made_with("a2", "alpha.safetensors"), _made_with("b2", "beta.safetensors")]
    tree = gallery.build_gallery_tree(kept)
    pane, _scroll = _pane(qtbot, kept)
    pane.set_model(kept, {LANDSCAPE: tree}, kept, [], deleted)
    trash = FolderCollection(TRASH_KEY, _models(tree)["alpha"].key).key

    pane.show_collection(trash, LANDSCAPE)

    assert pane.listed_prompt_ids() == ["a2"]
    assert [row["prompt_id"] for row in pane.rows_for_collection(oriented_key(trash, LANDSCAPE))]         == ["a2"]


def _in_flight(prompt_id, checkpoint):
    return {**_made_with(prompt_id, checkpoint), "status": "running", "output_files": None}


def test_a_folders_latest_leads_with_only_its_own_work_in_flight(qtbot):
    rows = [_made_with("a1", "alpha.safetensors"), _in_flight("a2", "alpha.safetensors"),
            _made_with("b1", "beta.safetensors"), _in_flight("b2", "beta.safetensors")]
    tree = gallery.build_gallery_tree(rows)
    pane, _scroll = _pane(qtbot, rows)
    pane.set_model(rows[::2], {LANDSCAPE: tree}, rows, [], [])

    pane.show_collection(FolderCollection(RECENTS_KEY, _models(tree)["alpha"].key).key, LANDSCAPE)

    assert list(pane._inflight_cards) == ["a2"]


def test_a_folders_favorites_are_its_starred_pictures_and_the_favorite_folders_below_it(qtbot):
    rows = [_made_with("a1", "alpha.safetensors", starred=1),
            _made_with("a2", "alpha.safetensors", prompt="scene two"),
            _made_with("b1", "beta.safetensors", starred=1)]
    tree = gallery.build_gallery_tree(rows)
    alpha = _models(tree)["alpha"]
    (lora,) = gallery.child_groups(alpha)
    (scene_two,) = [leaf for leaf in gallery.child_groups(lora) if leaf.rows[0]["prompt_id"] == "a2"]
    scene_two.favorite = True
    pane, _scroll = _pane(qtbot, rows)
    pane.set_model(rows, {LANDSCAPE: tree}, rows, [], [])
    favorites = FolderCollection(FAVORITES_KEY, alpha.key).key

    pane.show_collection(favorites, LANDSCAPE)

    assert pane.listed_prompt_ids() == ["a1"]
    assert pane._listed_folders == [scene_two.key]
    assert sorted(row["prompt_id"] for row in
                  pane.rows_for_collection(oriented_key(favorites, LANDSCAPE))) == ["a1", "a2"]


def _enhanced_made_with(prompt_id, checkpoint):
    row = _made_with(prompt_id, checkpoint)
    row["original_files"] = json.dumps([{"filename": f"sdxl_t2i_{prompt_id}_base.png"}])
    return row


def test_a_folders_enhanced_lists_the_enhanced_images_under_it(qtbot):
    rows = [_enhanced_made_with("a1", "alpha.safetensors"),
            _made_with("a2", "alpha.safetensors", prompt="scene two"),
            _enhanced_made_with("b1", "beta.safetensors")]
    tree = gallery.build_gallery_tree(rows)
    pane, _scroll = _pane(qtbot, rows)
    pane.set_model(rows, {LANDSCAPE: tree}, rows, [], [])
    enhanced = FolderCollection(ENHANCED_KEY, _models(tree)["alpha"].key).key

    pane.show_collection(enhanced, LANDSCAPE)

    assert pane.listed_prompt_ids() == ["a1"]
    assert [row["prompt_id"] for row in
            pane.rows_for_collection(oriented_key(enhanced, LANDSCAPE))] == ["a1"]


def test_a_folders_experiments_are_the_ones_made_in_that_folder(qtbot):
    kept = [_made_with("a1", "alpha.safetensors"), _made_with("b1", "beta.safetensors")]
    tried = [_made_with("a2", "alpha.safetensors"), _made_with("b2", "beta.safetensors")]
    tree = gallery.build_gallery_tree(kept + tried)
    pane, _scroll = _pane(qtbot, kept + tried)
    pane.set_model(kept, {LANDSCAPE: tree}, kept + tried, tried, [])

    pane.show_collection(FolderCollection(EXPERIMENTS_KEY, _models(tree)["beta"].key).key, LANDSCAPE)

    assert pane.listed_prompt_ids() == ["b2"]


def test_a_folders_requests_are_the_ones_that_landed_in_it(qtbot):
    rows = [_made_with("a1", "alpha.safetensors"), _made_with("b1", "beta.safetensors")]
    tree = gallery.build_gallery_tree(rows)
    pane, _scroll = _pane(qtbot, rows)
    pane.set_model(rows, {LANDSCAPE: tree}, rows, [], [],
                   request_items=[{"row": row} for row in rows])

    pane.show_collection(FolderCollection(REQUESTS_KEY, _models(tree)["alpha"].key).key, LANDSCAPE)

    assert pane.listed_prompt_ids() == ["a1"]


def _failed(prompt_id, checkpoint, prompt):
    return {**_made_with(prompt_id, checkpoint, prompt=prompt), "status": "error",
            "output_files": None}


def _folders_of_folders(tree):
    found = [gallery.ALL_KEY]

    def walk(groups):
        for group in groups:
            if gallery.child_groups(group):
                found.append(group.key)
                walk(gallery.child_groups(group))

    walk(tree)
    return found


def test_a_listing_asked_for_again_is_not_dealt_to_its_side_again(qtbot, monkeypatch):
    # Every collection of a side asks for its rows on each rebuild, and each ask
    # dealt the whole listing out to the side afresh: thirteen passes over the
    # library per rebuild for five collections.
    dealt = []
    filter_rows = browser_pane.filter_rows
    monkeypatch.setattr(browser_pane, "filter_rows",
                        lambda rows, side: dealt.append(side) or filter_rows(rows, side))
    rows = [_made_with("a1", "alpha.safetensors"), _made_with("b1", "beta.safetensors")]
    pane, _scroll = _pane(qtbot, rows)
    pane.set_model(rows, {LANDSCAPE: gallery.build_gallery_tree(rows)}, rows, [], [])
    latest = oriented_key(FolderCollection(RECENTS_KEY, gallery.ALL_KEY).key, LANDSCAPE)

    pane.collection_counts(LANDSCAPE)
    pane.rows_for_collection(latest)
    once = len(dealt)
    pane.collection_counts(LANDSCAPE)
    pane.rows_for_collection(latest)

    assert len(dealt) == once


def test_a_redraw_of_the_latest_collection_keeps_the_tiles_it_already_drew(qtbot):
    # Every landing redraws the collection from a fresh model, and every tile the
    # user had scrolled into view was built again from its picture.
    rows = [_row("a", 1), _row("b", 2)]
    pane, _scroll = _pane(qtbot, rows)
    _open_recents(pane, rows)
    drawn = dict(pane._thumb_widgets)

    _open_recents(pane, [dict(row) for row in rows])

    assert pane._thumb_widgets == drawn
    assert all(not sip.isdeleted(tile) and tile.parent() is not None for tile in drawn.values())


def test_a_kept_tile_takes_the_star_its_row_now_wears(qtbot):
    rows = [_row("a", 1)]
    pane, _scroll = _pane(qtbot, rows)
    _open_recents(pane, rows)
    tile = pane._thumb_widgets["a"]

    _open_recents(pane, [{**rows[0], "starred": 1}])

    assert pane._thumb_widgets["a"] is tile
    assert tile._favorite is True


def test_a_tile_whose_picture_changed_is_drawn_afresh(qtbot):
    rows = [_row("a", 1)]
    pane, _scroll = _pane(qtbot, rows)
    _open_recents(pane, rows)
    tile = pane._thumb_widgets["a"]

    _open_recents(pane, [{**rows[0], "thumbnail_path": "elsewhere.jpg"}])

    assert pane._thumb_widgets["a"] is not tile


def test_a_tile_drawn_for_a_folder_is_not_taken_for_a_collection(qtbot):
    # A folder's tile and a collection's answer a double-click differently, so one is
    # never wired for the other.
    rows = [_made_with("a1", "alpha.safetensors")]
    tree = gallery.build_gallery_tree(rows)
    (lora,) = gallery.child_groups(_models(tree)["alpha"])
    (leaf,) = gallery.child_groups(lora)
    pane, _scroll = _pane(qtbot, rows)
    pane.set_model(rows, {LANDSCAPE: tree}, rows, [], [])
    pane.show_thumbnails(leaf)
    in_folder = pane._thumb_widgets["a1"]

    pane.show_collection(RECENTS_KEY, LANDSCAPE)

    assert pane._thumb_widgets["a1"] is not in_folder


def test_each_folders_collection_counts_what_that_collection_lists(qtbot):
    rows = [_made_with("a1", "alpha.safetensors", starred=1),
            _made_with("a2", "alpha.safetensors", prompt="scene two"),
            _made_with("b1", "beta.safetensors"),
            _made_with("b2", "beta.safetensors", prompt="scene two")]
    listed = [*rows, _failed("b3", "beta.safetensors", "scene two")]
    tree = gallery.build_gallery_tree(rows)
    (lora,) = gallery.child_groups(_models(tree)["beta"])
    for leaf in gallery.child_groups(lora):
        leaf.favorite = leaf.rows[0]["prompt_id"] == "b2"
    deleted = [_made_with("a4", "alpha.safetensors"), _made_with("b4", "beta.safetensors")]
    pane, _scroll = _pane(qtbot, rows)
    pane.set_model(rows, {LANDSCAPE: tree}, listed, [rows[1]], deleted,
                   request_items=[{"row": rows[2]}, {"row": listed[4]}])

    counts = pane.collection_counts(LANDSCAPE)

    assert counts[FolderCollection(TRASH_KEY, _models(tree)["alpha"].key).key] == 1
    for folder in _folders_of_folders(tree):
        for collection in (FAVORITES_KEY, EXPERIMENTS_KEY, REQUESTS_KEY, TRASH_KEY):
            key = FolderCollection(collection, folder).key
            listing = pane.rows_for_collection(oriented_key(key, LANDSCAPE))
            assert counts.get(key, 0) == len(listing), key


def test_a_collection_square_wears_the_mark_its_row_wears(qtbot):
    rows = [_made_with("a1", "alpha.safetensors")]
    pane, scroll = _pane(qtbot, rows)
    pane.set_model(rows, {LANDSCAPE: gallery.build_gallery_tree(rows)}, rows, [], [])

    pane.show_folder_tiles([], collections=[oriented_key(TRASH_KEY, LANDSCAPE)])

    (tile,) = scroll.widget().findChildren(FolderTile)
    assert [label for label in tile.findChildren(QLabel)
            if label.toolTip() == "Trash" and not label.pixmap().isNull()]


def test_a_folders_collection_squares_stand_apart_from_its_folders_behind_a_heading_line(qtbot):
    rows = [_made_with("a1", "alpha.safetensors")]
    tree = gallery.build_gallery_tree(rows)
    pane, scroll = _pane(qtbot, rows)
    pane.set_model(rows, {LANDSCAPE: tree}, rows, [], [])

    pane.show_folder_tiles(tree, collections=[oriented_key(RECENTS_KEY, LANDSCAPE),
                                              oriented_key(TRASH_KEY, LANDSCAPE)])

    layout = scroll.widget().layout()
    shown = [layout.itemAt(index).widget() for index in range(layout.count())]
    assert [widget.objectName() for widget in shown] == [
        "folderTile", "folderTile", "tileGroupHeading", "folderTile"]
    assert not shown[2].text().strip()


def test_a_pane_with_nothing_drawn_marks_no_folder_square(qtbot):
    # A slideshow closing as the app itself closes hands its slide to a pane that has
    # nothing in it, and asking an empty pane for its squares took the app down.
    pane, _scroll = _pane(qtbot)

    assert pane.reveal_folder("image/sdxl_t2i/abc::landscape") is False

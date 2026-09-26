"""The browser pane, constructed alone — no GalleryView anywhere in sight.

Until the coupling inversion this file could not exist: BrowserPane took the
whole view and reached into it 93 times, so its 668 statements were exercised
only from inside tests/test_gallery_view.py. Now it takes six narrow
collaborators, and the stubs below are the whole of what standing one up
costs. The wider behavior — how the view answers the pane's signals — stays
pinned where the view is built; what lives here is the pane's own promise:
its selection model, its shelves, and what each shelf collects.

Fixture values are fabricated throughout (see CLAUDE.md).
"""
from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QLabel, QWidget

from origenerator import gallery
from origenerator.gallery.shelves import (
    EXPERIMENTS_KEY,
    FAVORITES_KEY,
    RECENTS_KEY,
    REQUESTS_KEY,
    TRASH_KEY,
    FolderShelf,
)
from origenerator.gui.browser_pane import (
    BrowserPane,
    BrowserScrollArea,
    LeadTiles,
    PaneHost,
    TreeNavigation,
)
from origenerator.gui.folder_tile import FolderTile
from origenerator.gui.inflight import InFlightItem, RunReading
from origenerator.gui.thumbnail_widget import ThumbnailWidget
from origenerator.orientation import LANDSCAPE, oriented_key

_NO_MOD = Qt.KeyboardModifier.NoModifier
_CTRL = Qt.KeyboardModifier.ControlModifier
_SHIFT = Qt.KeyboardModifier.ShiftModifier


def _row(prompt_id, seed, created_at=None):
    """One finished, fabricated image row — the least a shelf tile needs."""
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


class _StubReroll:
    def __init__(self):
        self.jobs_by_folder = {}
        self.queue_order = []

    def held_jobs(self):
        return []

    def job_for(self, key):
        return None


class _StubAuto:
    def is_active(self, key):
        return False


def _pane(qtbot, rows=(), lead_tiles=lambda group: LeadTiles()):
    scroll = BrowserScrollArea()
    qtbot.addWidget(scroll)
    pane = BrowserPane(
        scroll, _StubDB(rows), _StubReroll(), _StubAuto(),
        TreeNavigation(
            selected_folder_key=lambda: None,
            folder_context=lambda key: "",
            group_for_key=lambda key: None,
        ),
        PaneHost(
            media_types=lambda: {"image", "video"},
            image_rows=list,
            animated_preview=lambda row: None,
            enhancing_run=lambda row: None,
            enhance_settings=lambda: gallery.EnhanceSettings(),
            experiments_enabled=lambda: False,
            lead_tiles=lead_tiles,
        ),
    )
    return pane, scroll


def _open_recents(pane, rows):
    pane.set_model(rows, {}, [], [], [])
    pane.show_shelf(RECENTS_KEY)


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
    assert pane.visible_prompt_ids() == []


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


def test_recents_draws_a_page_at_a_time(qtbot):
    rows = [_row(f"g{n}", n) for n in range(1, 61)]
    pane, _scroll = _pane(qtbot, rows)
    _open_recents(pane, rows)

    # One page of the sixty, newest-first order preserved from the model.
    assert len(pane.visible_prompt_ids()) == 50
    assert pane.visible_prompt_ids()[0] == "g1"


def test_latest_heads_each_batch_with_when_it_was_made(qtbot):
    rows = [_row("g1", 1, "2026-09-12 23:00:00"), _row("g2", 2, "2026-09-12 22:50:00"),
            _row("g3", 3, "2026-09-12 19:00:00")]
    pane, scroll = _pane(qtbot, rows)
    _open_recents(pane, rows)

    first, _, second = gallery.section_headings(rows)
    assert _shown_in_order(scroll) == [first, "g1", "g2", second, "g3"]


def test_latest_opens_on_its_first_heading_with_the_work_still_running_beneath_it(
        qtbot, monkeypatch):
    rows = [_row("g1", 1, _ago(minutes=5))]
    pane, scroll = _pane(qtbot, rows)
    running = InFlightItem(key="j1", caption="scene one",
                           reading=RunReading(status="running"),
                           reveal=lambda: None, media_type="image")
    monkeypatch.setattr(pane, "inflight_items", lambda rows=None, requests=None: [running])
    _open_recents(pane, rows)

    [heading] = gallery.section_headings(rows)
    assert _shown_in_order(scroll) == [heading, "InFlightCard", "g1"]


def test_latest_puts_work_started_long_after_the_newest_picture_in_a_now_section(
        qtbot, monkeypatch):
    rows = [_row("g1", 1, _ago(hours=5))]
    pane, scroll = _pane(qtbot, rows)
    running = InFlightItem(key="j1", caption="scene one",
                           reading=RunReading(status="running"),
                           reveal=lambda: None, media_type="image")
    monkeypatch.setattr(pane, "inflight_items", lambda rows=None, requests=None: [running])
    _open_recents(pane, rows)

    [heading] = gallery.section_headings(rows)
    assert _shown_in_order(scroll) == ["Now", "InFlightCard", heading, "g1"]


def test_a_later_page_of_latest_heads_only_the_batches_that_begin_on_it(qtbot):
    later = [_row(f"a{n}", n, f"2026-09-12 22:{59 - n:02d}:00") for n in range(55)]
    earlier = [_row(f"b{n}", n, f"2026-09-12 18:{59 - n:02d}:00") for n in range(5)]
    rows = later + earlier
    pane, scroll = _pane(qtbot, rows)
    _open_recents(pane, rows)

    pane._draw_recents_page(50)

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


def test_work_running_in_a_folder_made_a_long_while_ago_goes_in_the_now_section(
        qtbot, monkeypatch):
    running = dict(_row("r1", 2, _ago(minutes=1)), status="running",
                   output_files=json.dumps([]))
    finished = _row("g1", 1, _ago(hours=5))
    pane, scroll = _pane(qtbot, [running, finished])
    card = InFlightItem(key="r1", caption="scene one", reading=RunReading(status="running"),
                        reveal=lambda: None, media_type="image")
    monkeypatch.setattr(pane, "inflight_items", lambda rows=None, requests=None: [card])

    pane.show_thumbnails(gallery.SettingsGroup(key="k1", label="scene one",
                                               rows=[running, finished]))

    [heading] = gallery.section_headings([finished])
    assert _shown_in_order(scroll) == ["Now", "InFlightCard", heading, "g1"]


def test_the_experiments_shelf_heads_each_batch_it_collected(qtbot):
    rows = [_row("e1", 1, "2026-09-12 23:00:00"), _row("e2", 2, "2026-09-12 19:00:00")]
    pane, scroll = _pane(qtbot, rows)
    pane.set_model([], {}, [], rows, [])

    pane.show_shelf(EXPERIMENTS_KEY)

    first, second = gallery.section_headings(rows)
    assert _shown_in_order(scroll) == [first, "e1", second, "e2"]


def test_the_requests_shelf_heads_each_batch_of_what_was_asked_for(qtbot):
    rows = [_row("r1", 1, "2026-09-12 23:00:00"), _row("r2", 2, "2026-09-12 19:00:00")]
    pane, scroll = _pane(qtbot, rows)
    pane.set_model([], {}, [], [], [], request_items=[{"row": row} for row in rows])

    pane.show_shelf(REQUESTS_KEY)

    first, second = gallery.section_headings(rows)
    assert _shown_in_order(scroll) == [first, "r1", second, "r2"]


def test_rows_for_shelf_answers_by_name_not_by_what_is_on_screen(qtbot):
    recents = [_row("g1", 1)]
    held = [_row("d1", 9)]
    pane, _scroll = _pane(qtbot, recents)
    pane.set_model(recents, {}, [], [], held)
    pane.show_shelf(RECENTS_KEY)

    assert [r["prompt_id"] for r in pane.rows_for_shelf(TRASH_KEY)] == ["d1"]


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
    (workflow,) = tree
    return {model.label: model for model in gallery.child_groups(workflow)}


def test_a_folders_latest_lists_only_what_that_folder_holds(qtbot):
    rows = [_made_with("a1", "alpha.safetensors"), _made_with("b1", "beta.safetensors")]
    tree = gallery.build_gallery_tree(rows)
    pane, _scroll = _pane(qtbot, rows)
    pane.set_model(rows, {LANDSCAPE: tree}, rows, [], [])

    pane.show_shelf(FolderShelf(RECENTS_KEY, _models(tree)["alpha"].key).key, LANDSCAPE)

    assert pane.visible_prompt_ids() == ["a1"]


def test_a_folders_trash_holds_what_was_deleted_from_that_folder(qtbot):
    kept = [_made_with("a1", "alpha.safetensors"), _made_with("b1", "beta.safetensors")]
    deleted = [_made_with("a2", "alpha.safetensors"), _made_with("b2", "beta.safetensors")]
    tree = gallery.build_gallery_tree(kept)
    pane, _scroll = _pane(qtbot, kept)
    pane.set_model(kept, {LANDSCAPE: tree}, kept, [], deleted)
    trash = FolderShelf(TRASH_KEY, _models(tree)["alpha"].key).key

    pane.show_shelf(trash, LANDSCAPE)

    assert pane.visible_prompt_ids() == ["a2"]
    assert [row["prompt_id"] for row in pane.rows_for_shelf(oriented_key(trash, LANDSCAPE))]         == ["a2"]


def _in_flight(prompt_id, checkpoint):
    return {**_made_with(prompt_id, checkpoint), "status": "running", "output_files": None}


def _card(prompt_id):
    return InFlightItem(key=prompt_id, caption="scene one", media_type="image",
                        reading=RunReading(status="running"), reveal=lambda: None)


def test_a_folders_latest_leads_with_only_its_own_work_in_flight(qtbot, monkeypatch):
    rows = [_made_with("a1", "alpha.safetensors"), _in_flight("a2", "alpha.safetensors"),
            _made_with("b1", "beta.safetensors"), _in_flight("b2", "beta.safetensors")]
    tree = gallery.build_gallery_tree(rows)
    pane, _scroll = _pane(qtbot, rows)
    pane.set_model(rows[::2], {LANDSCAPE: tree}, rows, [], [])
    monkeypatch.setattr(pane, "inflight_items",
                        lambda rows=None, requests=None: [_card("a2"), _card("b2")])

    pane.show_shelf(FolderShelf(RECENTS_KEY, _models(tree)["alpha"].key).key, LANDSCAPE)

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
    favorites = FolderShelf(FAVORITES_KEY, alpha.key).key

    pane.show_shelf(favorites, LANDSCAPE)

    assert pane.visible_prompt_ids() == ["a1"]
    assert pane._visible_keys == [scene_two.key]
    assert sorted(row["prompt_id"] for row in
                  pane.rows_for_shelf(oriented_key(favorites, LANDSCAPE))) == ["a1", "a2"]


def test_a_folders_experiments_are_the_ones_made_in_that_folder(qtbot):
    kept = [_made_with("a1", "alpha.safetensors"), _made_with("b1", "beta.safetensors")]
    tried = [_made_with("a2", "alpha.safetensors"), _made_with("b2", "beta.safetensors")]
    tree = gallery.build_gallery_tree(kept + tried)
    pane, _scroll = _pane(qtbot, kept + tried)
    pane.set_model(kept, {LANDSCAPE: tree}, kept + tried, tried, [])

    pane.show_shelf(FolderShelf(EXPERIMENTS_KEY, _models(tree)["beta"].key).key, LANDSCAPE)

    assert pane.visible_prompt_ids() == ["b2"]


def test_a_folders_requests_are_the_ones_that_landed_in_it(qtbot):
    rows = [_made_with("a1", "alpha.safetensors"), _made_with("b1", "beta.safetensors")]
    tree = gallery.build_gallery_tree(rows)
    pane, _scroll = _pane(qtbot, rows)
    pane.set_model(rows, {LANDSCAPE: tree}, rows, [], [],
                   request_items=[{"row": row} for row in rows])

    pane.show_shelf(FolderShelf(REQUESTS_KEY, _models(tree)["alpha"].key).key, LANDSCAPE)

    assert pane.visible_prompt_ids() == ["a1"]


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


def test_each_folders_shelf_counts_what_that_shelf_lists(qtbot):
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

    counts = pane.shelf_counts(LANDSCAPE)

    assert counts[FolderShelf(TRASH_KEY, _models(tree)["alpha"].key).key] == 1
    for folder in _folders_of_folders(tree):
        for shelf in (FAVORITES_KEY, EXPERIMENTS_KEY, REQUESTS_KEY, TRASH_KEY):
            key = FolderShelf(shelf, folder).key
            listing = pane.rows_for_shelf(oriented_key(key, LANDSCAPE))
            assert counts.get(key, 0) == len(listing), key


def test_a_shelf_square_wears_the_mark_its_row_wears(qtbot):
    rows = [_made_with("a1", "alpha.safetensors")]
    pane, scroll = _pane(qtbot, rows)
    pane.set_model(rows, {LANDSCAPE: gallery.build_gallery_tree(rows)}, rows, [], [])

    pane.show_folder_tiles([], shelves=[oriented_key(TRASH_KEY, LANDSCAPE)])

    (tile,) = scroll.widget().findChildren(FolderTile)
    assert [label for label in tile.findChildren(QLabel)
            if label.toolTip() == "Trash" and not label.pixmap().isNull()]


def test_a_folders_shelf_squares_stand_apart_from_its_folders_behind_a_heading_line(qtbot):
    rows = [_made_with("a1", "alpha.safetensors")]
    tree = gallery.build_gallery_tree(rows)
    pane, scroll = _pane(qtbot, rows)
    pane.set_model(rows, {LANDSCAPE: tree}, rows, [], [])

    pane.show_folder_tiles(tree, shelves=[oriented_key(RECENTS_KEY, LANDSCAPE),
                                          oriented_key(TRASH_KEY, LANDSCAPE)])

    layout = scroll.widget().layout()
    shown = [layout.itemAt(index).widget() for index in range(layout.count())]
    assert [widget.objectName() for widget in shown] == [
        "folderTile", "folderTile", "tileGroupHeading", "folderTile"]
    assert not shown[2].text().strip()

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

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QLabel, QWidget

from origenerator import gallery
from origenerator.gui.browser_pane import (
    BrowserPane,
    BrowserScrollArea,
    PaneHost,
    TreeNavigation,
)
from origenerator.gui.gallery_tree import (
    EXPERIMENTS_KEY,
    RECENTS_KEY,
    REQUESTS_KEY,
    TRASH_KEY,
)
from origenerator.gui.inflight import InFlightItem
from origenerator.gui.thumbnail_widget import ThumbnailWidget

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


def _pane(qtbot, rows=(), add_lead_tiles=lambda flow, group: None):
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
            add_lead_tiles=add_lead_tiles,
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
    rows = [_row("g1", 1, "2026-09-12 23:00:00")]
    pane, scroll = _pane(qtbot, rows)
    running = InFlightItem(key="j1", caption="scene one", status="running", frame=None,
                           reveal=lambda: None, media_type="image")
    monkeypatch.setattr(pane, "inflight_items", lambda rows=None, requests=None: [running])
    _open_recents(pane, rows)

    [heading] = gallery.section_headings(rows)
    assert _shown_in_order(scroll) == [heading, "InFlightCard", "g1"]


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


def test_a_folders_grid_heads_its_batches_with_its_lead_tiles_under_the_first(qtbot):
    rows = [_row("g1", 1, "2026-09-12 23:00:00"), _row("g2", 2, "2026-09-12 19:00:00")]
    pane, scroll = _pane(qtbot, rows,
                         add_lead_tiles=lambda flow, group: flow.addWidget(QLabel("lead")))

    pane.show_thumbnails(gallery.SettingsGroup(key="k1", label="scene one", rows=rows))

    first, second = gallery.section_headings(rows)
    assert _shown_in_order(scroll) == [first, "lead", "g1", second, "g2"]


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

from __future__ import annotations

import json
import os
import re
from dataclasses import FrozenInstanceError
from datetime import datetime
from itertools import pairwise
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from PIL import Image
from PyQt6 import sip
from PyQt6.QtCore import QPoint, QPointF, QSize, Qt
from PyQt6.QtGui import (
    QColor,
    QDropEvent,
    QImage,
    QPalette,
    QPixmap,
    QTextCursor,
    QTextDocument,
    QTextDocumentFragment,
)
from PyQt6.QtWidgets import (
    QApplication,
    QFormLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QSplitter,
    QWidget,
)
from shared_ui.colors import BG_PRIMARY, BG_SECONDARY, BLUE, TEXT_MUTED, TEXT_PRIMARY, YELLOW
from shared_ui.icons import inline_icon
from shared_ui.spacing import GAP_MEDIUM
from shared_ui.tick_control import TickControl

import origenerator.setting_advice as advice_module
import origenerator.workflows.derived_size as ds
import origenerator.workflows.model_dropdowns as model_dropdowns_module
from origenerator import (
    config,
    evolver_export,
    gallery,
    library_views,
    look_training,
    osr2_driver,
    prompt_edit,
)
from origenerator import export_lane as export_lane_module
from origenerator.action_vocabulary import vocabulary
from origenerator.box_breaks import BOX_BREAK
from origenerator.comfyui_client import ComfyUIClient
from origenerator.config import EVOLVER_INBOX_DIR, EVOLVER_SOURCE, GENAU_SOURCE
from origenerator.db import Database, NewGeneration, NewRequest
from origenerator.db_requests import Turn
from origenerator.funscript import (
    funscript_path_for,
    synthesize_actions,
    write_funscript,
)
from origenerator.gallery import media_type_of_row as gallery_media_type
from origenerator.gallery.keys import folder_id, settings_key
from origenerator.gallery.tree import settings_folder_key
from origenerator.generation_config import ConfigSnapshot
from origenerator.generation_state import GenerationSource
from origenerator.gui import corner_buttons, diff_text, icons
from origenerator.gui import generate_tab as generate_tab_module
from origenerator.gui import modify_batch as modify_batch_module
from origenerator.gui.action_row import SIDE_LABELS, action_checkbox, action_pills
from origenerator.gui.collapsible_section import CollapsibleSection
from origenerator.gui.drags import under_way
from origenerator.gui.drop_style import LIT
from origenerator.gui.eliding import ElidingLabel
from origenerator.gui.enhance_versions import RunningEnhancement, _AddRow, _PendingRow, _VersionRow
from origenerator.gui.generate_tab import TYPICAL_TIME, GenerateTab
from origenerator.gui.generation_drag import generation_mime
from origenerator.gui.label_cells import LabelCell
from origenerator.gui.look_training_controller import LookTrainingController
from origenerator.gui.param_form import STRENGTH_ONE_HELP, ParamForm
from origenerator.gui.pills import Pill
from origenerator.gui.source_tile import SourceTile
from origenerator.gui.stylesheet import build_stylesheet
from origenerator.gui.tracked_prompt import _Tracker
from origenerator.item_actions import ItemActions, actions_of
from origenerator.item_names import ItemNames
from origenerator.library_views import TabViews
from origenerator.media import MediaType
from origenerator.output_places import OutputPlaces
from origenerator.outside_videos import FrameFolders, OutsideVideo, Record, rows_bringing_in
from origenerator.prompt_tokens import CUT_OFF, READ_IN_PIECES
from origenerator.workflows import WORKFLOW_REGISTRY, offered_workflows
from origenerator.workflows.base import story_of
from origenerator.workflows.derived_size import scale_to_total_pixels
from origenerator.workflows.model_arch import KREA2, WAN
from origenerator.workflows.model_files import NO_LORA
from tests import drops
from tests.comfyui_folders import SUITE_FOLDERS
from tests.gallery_view_support import _struck_and_lit
from tests.related_links import source_tile
from tests.text_readers import clap_reader, clip_reader, word_reader, word_reading
from tests.thumbnail_rows import looping_video, painted_row, where_the_thumbnail_is


@pytest.fixture
def blank_panel(qtbot, tmp_path):
    db = Database(tmp_path / "test.db")
    p = GenerateTab(ComfyUIClient(folders=SUITE_FOLDERS), db)
    qtbot.addWidget(p)
    return p


@pytest.fixture
def app_chrome():
    app = QApplication.instance()
    prior = app.styleSheet()
    app.setStyleSheet(build_stylesheet())
    yield
    app.setStyleSheet(prior)


@pytest.fixture
def tab(blank_panel):
    blank_panel._workflow_dropdown.setCurrentIndex(_dropdown_index(blank_panel, "sdxl_t2i"))
    return blank_panel


def _dropdown_index(tab, key):
    for i in range(tab._workflow_dropdown.count()):
        if tab._workflow_dropdown.itemData(i) == key:
            return i
    raise AssertionError(f"workflow {key} not in the dropdown")


def _is_descendant(widget, ancestor) -> bool:
    node = widget.parent()
    while node is not None:
        if node is ancestor:
            return True
        node = node.parent()
    return False


def test_the_panel_is_one_column_with_no_side_pane(tab):
    assert tab.findChildren(QSplitter) == [tab._media_split, tab._settings_split]
    assert tab._media_split.orientation() == Qt.Orientation.Vertical


def test_the_column_reads_preview_then_generate_then_settings(tab):
    tab.show()
    tab.resize(700, 800)
    QApplication.processEvents()

    def span(widget):
        top = widget.mapTo(tab, QPoint(0, 0)).y()
        return top, top + widget.height()

    _, preview_foot = span(tab._viewport)
    line_top, line_foot = span(tab._media_split.handle(1))
    generate_top, generate_foot = span(tab._generate_btn.parentWidget())
    settings_top, _ = span(tab._settings_scroll)
    assert tab._viewport_pane.isAncestorOf(tab._generate_btn), (
        "Generate heads the settings rather than trailing them in the lower right corner, where "
        "Windows pops its messages up over whatever is there")
    assert preview_foot <= generate_top < generate_foot <= line_top < line_foot <= settings_top


def test_a_new_tab_gives_the_preview_five_eighths_and_the_settings_and_metadata_three_sixteenths_each(
        saved_panel):
    tab, db = saved_panel
    tab.resize(700, 1200)
    tab.show()
    QApplication.processEvents()
    image = _image_row(db)
    tab.show_saved_generation(image, [image])
    QApplication.processEvents()

    preview, rest = tab._media_split.sizes()
    settings, item = tab._settings_split.sizes()
    assert abs(5 * rest - 3 * preview) <= 16
    assert abs(settings - item) <= 4


def test_the_line_between_the_preview_and_the_settings_is_a_drag_handle(tab):
    split = tab._media_split

    assert split.handleWidth() > 0
    assert not split.childrenCollapsible()
    split.setSizes([500, 200])
    assert split.sizes()[0] > split.sizes()[1]


def test_a_narrow_pane_squeezes_the_fields_instead_of_scrolling_sideways(tab):
    for section in tab._param_form._sections.values():
        section.set_collapsed(False)
    tab.show()

    for width in (600, 420, 300):
        tab.resize(width, 800)
        QApplication.processEvents()
        assert not tab._settings_scroll.horizontalScrollBar().isVisible(), f"at {width}px"


def test_nothing_in_the_form_is_laid_out_past_the_column_it_sits_in(blank_panel):
    tab = blank_panel
    tab._workflow_dropdown.setCurrentIndex(_dropdown_index(tab, "wan22_i2v"))
    for section in tab._param_form._sections.values():
        section.set_collapsed(False)
    tab.show()

    host = tab._settings_scroll.widget()
    for width in (600, 420, 320, 260, 240):
        tab.resize(width, 800)
        QApplication.processEvents()
        over = []

        def walk(widget, over=over):
            if not widget.isVisible():
                return
            right = widget.mapTo(host, widget.rect().topRight()).x()
            if right >= host.width():
                over.append((type(widget).__name__,
                             getattr(widget, "text", lambda: "")(),
                             right - host.width()))
            for child in widget.children():
                if child.isWidgetType():
                    walk(child)

        walk(host)
        assert not over, f"at {width}px: {over[:3]}"


def _names_its_setting(label: ElidingLabel) -> bool:
    shown = label.display_text(label.contentsRect().width()).removesuffix("…")
    return bool(shown) and label.text().startswith(shown)


@pytest.mark.parametrize("workflow", [None, "sdxl_t2i", "wan22_i2v", "flux_t2i_upscaled"])
def test_a_narrow_pane_shortens_its_labels_rather_than_dropping_them(
        app_chrome, blank_panel, workflow):
    # Qt's QFormLayout gives its labels the widest one's width when a row fits beside its field and no width at all when none does.
    tab = blank_panel
    if workflow is not None:
        tab._workflow_dropdown.setCurrentIndex(_dropdown_index(tab, workflow))
        for section in tab._param_form._sections.values():
            section.set_collapsed(False)
    tab.show()
    QApplication.processEvents()

    for width in (600, 420, 330, tab.minimumSizeHint().width()):
        tab.resize(width, 800)
        QApplication.processEvents()
        labels = [cell.findChild(ElidingLabel) for cell in tab.findChildren(LabelCell)
                  if cell.isVisible()]
        assert labels
        unnamed = [label.text() for label in labels if not _names_its_setting(label)]
        assert not unnamed, f"at {width}px: {unnamed}"


@pytest.mark.parametrize("workflow", ["sdxl_t2i", "wan22_i2v", "wan22_animate"])
def test_a_narrow_pane_shortens_a_label_before_it_squeezes_a_field(
        app_chrome, blank_panel, workflow):
    # Qt's QFormLayout kept a section's labels whole while any one of its fields still fit beside them, and squeezed the rest.
    tab = blank_panel
    tab._workflow_dropdown.setCurrentIndex(_dropdown_index(tab, workflow))
    sections = tab._param_form._sections.values()
    for section in sections:
        section.set_collapsed(False)
    tab.show()
    QApplication.processEvents()

    for width in (600, 500, 420, 380, 330, tab.minimumSizeHint().width()):
        tab.resize(width, 800)
        QApplication.processEvents()
        squeezed = []
        for section in sections:
            form = section.content_form()
            for row in range(form.rowCount()):
                label = form.itemAt(row, QFormLayout.ItemRole.LabelRole)
                field = form.itemAt(row, QFormLayout.ItemRole.FieldRole)
                if (section.isVisible() and form.isRowVisible(row)
                        and label is not None and field is not None
                        and field.geometry().width() < field.minimumSize().width()):
                    squeezed.append((label.widget().findChild(ElidingLabel).text(),
                                     field.geometry().width(), field.minimumSize().width()))
        assert not squeezed, f"at {width}px: {squeezed}"


def test_the_pane_will_not_be_squeezed_narrower_than_its_settings(app_chrome, blank_panel):
    tab = blank_panel
    blank_floor = tab._contents_floor()
    tab._workflow_dropdown.setCurrentIndex(_dropdown_index(tab, "wan22_i2v"))
    for section in tab._param_form._sections.values():
        section.set_collapsed(False)
    tab.show()
    QApplication.processEvents()

    assert tab._contents_floor() > blank_floor
    floor = tab.minimumSizeHint().width()
    assert floor >= tab._contents_floor()

    tab.resize(floor, 800)
    QApplication.processEvents()
    assert not tab._settings_scroll.horizontalScrollBar().isVisible()
    assert tab._settings_scroll.viewport().width() >= tab._settings_scroll.widget().minimumSizeHint().width()


def test_the_floor_stops_at_the_width_a_monitor_third_can_give_the_pane(app_chrome, blank_panel):
    tab = blank_panel
    wider_than_a_monitor_third = QWidget()
    wider_than_a_monitor_third.setMinimumWidth(3 * generate_tab_module._FLOOR_CAP)
    tab._settings_scroll.widget().layout().addWidget(wider_than_a_monitor_third)

    assert tab._contents_floor() > generate_tab_module._FLOOR_CAP
    assert tab.minimumSizeHint().width() == generate_tab_module._FLOOR_CAP


def test_the_button_bank_wraps_rather_than_squeezing_its_labels(tab):
    tab._sent_note.setText(export_lane_module.KINO.sent_caption)
    buttons = [tab._sent_row, tab._cancel_btn, tab._generate_btn.parentWidget()]
    for button in buttons:
        button.show()
    tab.show()

    tab.resize(340, 800)
    QApplication.processEvents()

    for button in buttons:
        assert button.width() == button.sizeHint().width(), button
    assert len({button.y() for button in buttons}) > 1
    lines = {}
    for button in buttons:
        lines[button.y()] = max(lines.get(button.y(), 0), button.x() + button.width())
    assert len(set(lines.values())) == 1


def test_the_pane_keeps_a_margin_round_its_contents(tab):
    margin_written_out = 8
    tab.show()
    tab.resize(700, 800)
    QApplication.processEvents()

    top_left = tab._viewport.mapTo(tab, tab._viewport.rect().topLeft())
    assert top_left.x() == margin_written_out
    assert top_left.y() == margin_written_out
    form = tab._form_host
    assert form.mapTo(tab, form.rect().topLeft()).x() == margin_written_out
    viewport = tab._settings_scroll.viewport()
    bar_side = viewport.mapTo(tab, viewport.rect().topRight()).x()
    assert bar_side - form.mapTo(tab, form.rect().topRight()).x() == margin_written_out
    generate = tab._generate_btn.parentWidget()
    assert tab.width() - generate.mapTo(tab, generate.rect().topRight()).x() - 1 == margin_written_out
    item_viewport = tab._item_scroll.viewport()
    lower = item_viewport.mapTo(tab, item_viewport.rect().bottomLeft()).y()
    assert tab.height() - lower - 1 == margin_written_out


def test_generate_and_the_top_setting_keep_clear_of_the_borders_round_them(tab):
    tab.show()
    tab.resize(700, 800)
    QApplication.processEvents()

    def span(widget):
        top = widget.mapTo(tab, QPoint(0, 0)).y()
        return top, top + widget.height()

    _, preview_foot = span(tab._viewport)
    generate_top, generate_foot = span(tab._generate_btn.parentWidget())
    line_top, line_foot = span(tab._media_split.handle(1))
    dropdown_top, _ = span(tab._workflow_dropdown)
    assert generate_top - preview_foot >= 8
    assert line_top - generate_foot >= 8
    assert dropdown_top - line_foot >= 8


def test_the_settings_handle_reaches_the_panes_own_border(tab):
    tab.show()
    tab.resize(700, 800)

    handle = tab._media_split.handle(1)
    left = handle.mapTo(tab, handle.rect().topLeft()).x()
    right = handle.mapTo(tab, handle.rect().topRight()).x()
    assert left == 0
    assert right == tab.width() - 1


def _layout_containing(root, widget):
    for i in range(root.count()):
        item = root.itemAt(i)
        if item.widget() is widget:
            return root
        sub = item.layout()
        if sub is not None and (found := _layout_containing(sub, widget)) is not None:
            return found
    return None


def test_the_settings_scroll_nearest_the_preview_with_the_item_under_a_border(tab):
    for widget in (tab._metadata_section, tab._related._requests,
                   tab._related._animations, tab._versions):
        assert _is_descendant(widget, tab._item_scroll)
    assert _is_descendant(tab._param_form, tab._settings_scroll)
    split = tab._settings_split
    assert (split.orientation(), split.widget(0), split.widget(1)) == (
        Qt.Orientation.Vertical, tab._settings_scroll, tab._item_scroll)


def _leaves_outside_sections(tab, scroll):
    body = scroll.widget()

    def in_a_section(widget):
        node = widget.parentWidget()
        while node is not None and node is not body:
            if isinstance(node, CollapsibleSection):
                return True
            node = node.parentWidget()
        return False

    return [type(widget).__name__ for widget in body.findChildren(QWidget)
            if widget.isVisibleTo(body) and not widget.findChildren(QWidget)
            and not in_a_section(widget)]


@pytest.mark.parametrize("shown", ["nothing", "image", "video"])
def test_nothing_on_a_tab_scrolls_outside_a_section(installed_models, saved_panel, shown):
    tab, db = saved_panel
    if shown != "nothing":
        row = (_image_made_with(db, "retired_checkpoint.safetensors") if shown == "image"
               else _video_row(db, input_image="sdxl_img1.png"))
        tab.show_saved_generation(row, [_image_row(db)])
    tab.resize(700, 1600)
    tab.show()
    QApplication.processEvents()

    assert (_leaves_outside_sections(tab, tab._settings_scroll),
            _leaves_outside_sections(tab, tab._item_scroll)) == ([], [])


def test_every_sections_labels_end_at_one_right_edge(app_chrome, installed_models, saved_panel):
    tab, db = saved_panel
    tab.show_saved_generation(_image_made_with(db, "retired_checkpoint.safetensors"),
                              [_image_row(db)])
    tab.resize(700, 1600)
    tab.show()
    QApplication.processEvents()

    edges = {cell.mapTo(tab, QPoint(cell.width(), 0)).x()
             for cell in tab.findChildren(LabelCell) if cell.isVisibleTo(tab)}
    assert len(edges) == 1


def test_the_metadata_leads_the_items_area_with_its_related_media_below(tab):
    body = tab._item_scroll.widget().layout()
    assert (body.indexOf(tab._metadata_section), body.indexOf(tab._related),
            body.indexOf(tab._versions)) == (0, 1, 2)


def test_the_lane_button_shares_the_button_bank_with_generate_and_cancel(tab):
    buttons = _layout_containing(tab._viewport_pane.layout(), tab._generate_btn.parentWidget())
    assert buttons is not None
    assert buttons.indexOf(tab._lane_button) != -1
    assert buttons.indexOf(tab._cancel_btn) != -1


def test_switching_workflow_detaches_the_old_form_at_once(tab):
    old_form = tab._param_form
    tab._workflow_dropdown.setCurrentIndex(_dropdown_index(tab, "flux_t2i_upscaled"))

    assert tab._param_form is not old_form
    assert old_form.parent() is None
    live = [f for f in tab._form_host.findChildren(ParamForm)
            if f.parent() is tab._form_host]
    assert live == [tab._param_form]


def test_switching_workflow_carries_over_the_users_edits(blank_panel):
    tab = blank_panel
    tab._workflow_dropdown.setCurrentIndex(_dropdown_index(tab, "wan22_flf2v_loop"))
    tab._param_form.set_values({
        "positive_prompt": "slow beta",
        "input_image": "start.png",
        "audio_prompt": "wet rhythm",
        "steps": 7,
    })

    tab._workflow_dropdown.setCurrentIndex(_dropdown_index(tab, "wan22_i2v"))

    values = tab._param_form.get_values()
    assert values["positive_prompt"] == "slow beta"
    assert values["input_image"] == "start.png"
    assert values["audio_prompt"] == "wet rhythm"
    assert values["steps"] == 7
    loop_defaults = WORKFLOW_REGISTRY["wan22_flf2v_loop"].default_params()
    i2v_defaults = WORKFLOW_REGISTRY["wan22_i2v"].default_params()
    assert values["shift_high"] == i2v_defaults["shift_high"] != loop_defaults["shift_high"]
    assert values["cfg_high"] == i2v_defaults["cfg_high"]


def test_i2v_workflow_form_gets_the_derived_size_deriver(blank_panel):
    tab = blank_panel
    tab._workflow_dropdown.setCurrentIndex(_dropdown_index(tab, "wan22_i2v"))
    form = tab._param_form
    assert form._size_deriver is not None
    assert "width" in form._present_keys["Size"]
    assert form._dim_stacks["width"].currentIndex() == 0
    assert form._unlock_btn is not None


def test_i2v_form_shows_the_measured_size_of_a_real_input_image(blank_panel, tmp_path,
                                                               monkeypatch):
    tab = blank_panel
    monkeypatch.setattr(ds, "COMFYUI_INPUT_DIR", tmp_path)
    Image.new("RGB", (1920, 1080), (128, 128, 128)).save(tmp_path / "wide.png")

    tab._workflow_dropdown.setCurrentIndex(_dropdown_index(tab, "wan22_i2v"))
    tab._param_form._widgets["input_image"].set_item("wide.png")

    width, height = scale_to_total_pixels(1920, 1080)
    assert tab._param_form._dim_value_labels["width"].text() == str(width)
    assert tab._param_form._dim_value_labels["height"].text() == str(height)


def test_manual_size_workflow_form_has_no_deriver(tab):
    tab._workflow_dropdown.setCurrentIndex(_dropdown_index(tab, "sdxl_t2i"))
    form = tab._param_form
    assert form._size_deriver is None
    assert form._unlock_btn is None


def test_tolerates_a_missing_client(qtbot, tmp_path):
    p = GenerateTab(None, Database(tmp_path / "t.db"))
    qtbot.addWidget(p)
    assert p._generate_btn.isEnabled() is False
    p._on_generate()


def test_cancel_button_sits_beside_generate_hidden_until_generating(tab):
    assert isinstance(tab._cancel_btn, QPushButton)
    assert _is_descendant(tab._cancel_btn, tab)
    assert tab._cancel_btn.parent() is tab._generate_btn.parentWidget().parent()
    assert tab._cancel_btn.isHidden()


def test_set_generating_offers_cancel_and_leaves_generate_to_the_folder(tab):
    tab.set_generating(True)
    assert tab._cancel_btn.isHidden() is False
    assert tab._generate_btn.isEnabled() is True
    tab.set_generating(False)
    assert tab._cancel_btn.isHidden() is True
    assert tab._generate_btn.isEnabled() is True


def test_the_cancel_hover_says_next_seed_while_the_folder_populates(tab):
    tab.set_generating(True, populating=True)
    assert tab._cancel_btn.text() == "Cancel"
    assert tab._cancel_btn.toolTip() == "Throw away this seed and start the next"

    tab.set_generating(True)
    assert tab._cancel_btn.toolTip() == "Cancel this generation"


def test_set_generating_false_keeps_generate_disabled_without_a_client(qtbot, tmp_path):
    p = GenerateTab(None, Database(tmp_path / "t.db"))
    qtbot.addWidget(p)
    p.set_generating(False)
    assert p._generate_btn.isEnabled() is False


def test_cancel_button_click_emits_cancel_requested(tab):
    got = []
    tab.cancel_requested.connect(lambda: got.append(True))
    tab.set_generating(True)
    tab._cancel_btn.click()
    assert got == [True]


def test_a_tabs_seed_drops_down_every_seed_the_library_used_newest_first(tab):
    for prompt_id, seed in (("older", 10), ("newer", 20)):
        tab._db.insert_generation(NewGeneration(
            prompt_id=prompt_id, workflow_name="sdxl_t2i",
            workflow_version=WORKFLOW_REGISTRY["sdxl_t2i"].version, seed=seed,
            params_json=json.dumps({"seed": seed}), workflow_json="{}"))
        tab._db.update_generation(prompt_id, status="completed", output_files=json.dumps(
            [{"filename": f"{prompt_id}.png", "subfolder": "image"}]))

    assert _seeds_listed(tab, "seed") == ["20", "10"]


def test_a_tabs_seed_dropdown_lists_only_the_seeds_of_the_kind_it_makes(tab, qtbot):
    _image_row(tab._db)
    _video_row(tab._db, noise_seed=30)
    video_tab = GenerateTab(ComfyUIClient(folders=SUITE_FOLDERS), tab._db)
    qtbot.addWidget(video_tab)
    video_tab._workflow_dropdown.setCurrentIndex(_dropdown_index(video_tab, "wan22_i2v"))

    assert _seeds_listed(tab, "seed") == ["1"]
    assert _seeds_listed(video_tab, "noise_seed") == ["30"]


def test_a_video_tabs_seed_dropdown_plays_the_videos_it_lists(blank_panel, qtbot, monkeypatch,
                                                              tmp_path):
    tab = blank_panel
    _video_row(tab._db, noise_seed=30)
    video = looping_video(tmp_path)
    monkeypatch.setattr(gallery, "animated_preview_if_made",
                        lambda row, *_folders: video if row["prompt_id"] == "vid1" else None)
    tab._workflow_dropdown.setCurrentIndex(_dropdown_index(tab, "wan22_i2v"))
    field = tab._param_form._widgets["noise_seed"]
    field.showPopup()
    first = painted_row(field, 0)
    middle = where_the_thumbnail_is(first).center()

    qtbot.waitUntil(lambda: painted_row(field, 0).pixel(middle) != first.pixel(middle),
                    timeout=3000)
    field.hidePopup()


def _seeds_listed(tab, key):
    field = tab._param_form._widgets[key]
    field.showPopup()
    listed = [field.itemText(row) for row in range(field.count())]
    field.hidePopup()
    return listed


def test_a_seed_drawn_by_ticking_random_heads_the_dropdown(tab):
    tab._param_form.set_values({"seed": 5})
    tab._param_form._randomize_checks["seed"].click()
    drawn = tab._param_form.get_values()["seed"]
    field = tab._param_form._widgets["seed"]

    field.showPopup()

    assert field.itemText(0) == str(drawn)
    field.hidePopup()


def test_the_seed_a_tab_picks_after_a_press_is_listed_only_once_it_is_used(tab):
    tab._on_generate()
    picked = tab._param_form.get_values()["seed"]

    assert str(picked) not in _seeds_listed(tab, "seed")


def test_a_drawn_seed_is_kept_at_the_size_the_tab_would_make(tab):
    tab._param_form.set_values({"seed": 5, "width": 832, "height": 1216})

    tab._param_form._randomize_checks["seed"].click()

    record = tab._db.list_seed_uses()[0]
    assert (record["width"], record["height"]) == (832, 1216)


def test_a_drawn_seed_is_kept_for_the_kind_of_item_the_tab_makes(tab):
    tab._param_form.set_values({"seed": 5})

    tab._param_form._randomize_checks["seed"].click()

    assert tab._db.list_seed_uses()[0]["media_type"] == MediaType.IMAGE


def test_use_random_seed_switches_the_seed_to_random(tab):
    tab.prefill("sdxl_t2i", {"seed": 99})
    assert tab._param_form.seed_is_random() is False
    tab.use_random_seed()
    assert tab._param_form.seed_is_random() is True


def test_picking_a_workflow_by_hand_announces_a_user_edit(blank_panel):
    edits = []
    blank_panel.user_edited.connect(lambda: edits.append(True))

    blank_panel._workflow_dropdown.setCurrentIndex(_dropdown_index(blank_panel, "sdxl_t2i"))

    assert edits, (
        "on a form with nothing to carry over, picking a workflow is the only sign of an edit there is")


def test_a_prefill_announces_no_user_edit(tab):
    edits = []
    tab.user_edited.connect(lambda: edits.append(True))

    tab.prefill("sdxl_t2i", {"seed": 99})

    assert edits == []


def test_the_generate_caption_is_re_read_on_a_timer_not_on_each_cue(tab):
    tab._caption_timer.stop()

    tab.refresh_generate_caption()

    assert tab._caption_timer.isActive(), (
        "whether a press would repeat a past generation needs every stored generation's settings, "
        "far too much to spend on each keystroke")
    assert tab._caption_timer.isSingleShot()


def test_the_outgoing_form_is_still_alive_when_the_prompt_fields_change_is_announced(tab):
    outgoing = tab._param_form
    alive_when_announced = []
    tab.prompt_fields_changed.connect(lambda: alive_when_announced.append(not sip.isdeleted(outgoing)))

    other = next(i for i in range(tab._workflow_dropdown.count())
                 if tab._workflow_dropdown.itemData(i) not in (None, "", "sdxl_t2i"))
    tab._workflow_dropdown.setCurrentIndex(other)

    assert alive_when_announced
    assert all(alive_when_announced)


def test_a_made_from_pair_already_on_show_is_not_painted_again(tab):
    painted = []
    tab.show_combination = painted.append
    pair = object()

    tab.show_live_source(pair)
    tab.show_live_source(pair)

    assert painted == [pair], (
        "built again at every poll, the pair would restart its video's loop from the first frame each second")


def test_a_wait_text_already_on_show_is_not_painted_again(tab):
    painted = []
    tab._viewport.show_message = lambda text, **_kwargs: painted.append(text)

    tab.show_live_wait("Loading the model")
    tab.show_live_wait("Loading the model")

    assert painted == ["Loading the model"]


def test_generates_dropdown_offers_powers_of_two_up_to_32_and_rests_on_one(tab):
    how_many = tab._how_many

    assert [how_many.itemText(i) for i in range(how_many.count())] == [
        "1", "2", "4", "8", "16", "32"]
    assert how_many.how_many() == 1


def test_generates_dropdown_says_on_hover_what_it_counts(tab):
    assert tab._how_many.toolTip() == "How many to make at once, each with its own seed"


def test_generates_dropdown_sits_flush_on_its_right_edge_at_its_height(tab, app_chrome):
    tab.show()
    QApplication.processEvents()
    generate, how_many = tab._generate_btn, tab._how_many

    assert how_many.x() == generate.x() + generate.width()
    assert (how_many.y(), how_many.height()) == (generate.y(), generate.height())


def test_generate_with_its_dropdown_stands_as_tall_as_the_buttons_beside_it(tab, app_chrome):
    tab._cancel_btn.show()
    tab.show()
    QApplication.processEvents()

    assert tab._generate_btn.parentWidget().height() == tab._cancel_btn.height()


def _left_of_the_number(tab):
    pair = tab._generate_btn.parentWidget()
    return pair.grab().toImage().pixelColor(tab._how_many.x() + 4, pair.height() // 2)


def _its_folder_is_making_one(tab):
    tab.set_making_one_check(lambda _config: True)
    tab.reread_generate_button()


def test_generates_dropdown_wears_generates_blue_and_grays_out_with_it(tab, app_chrome):
    tab.show()
    QApplication.processEvents()
    assert _left_of_the_number(tab) == BLUE

    _its_folder_is_making_one(tab)

    assert _left_of_the_number(tab) == BG_SECONDARY


def _arrow_inks(widget):
    image = widget.grab().toImage()
    return {image.pixelColor(x, y).name()
            for x in range(image.width() - 18, image.width())
            for y in range(image.height())}


def test_generates_dropdown_draws_its_arrow_in_generates_ink(tab, app_chrome):
    tab.show()
    QApplication.processEvents()
    assert TEXT_PRIMARY.name() in _arrow_inks(tab._how_many)

    _its_folder_is_making_one(tab)

    assert TEXT_MUTED.name() in _arrow_inks(tab._how_many)


def test_generate_asks_for_as_many_as_its_dropdown_says_each_on_a_seed_of_its_own(tab):
    shown = tab._param_form.get_values()["seed"]
    tab._how_many.set_how_many(4)
    requested = []
    tab.generate_requested.connect(lambda wf, batch: requested.append(batch))

    tab._on_generate()

    (batch,) = requested
    seeds = [params["seed"] for params in batch]
    assert seeds[0] == shown
    assert len(set(seeds)) == 4


def test_a_pinned_seed_is_made_first_and_the_rest_of_the_press_draw_their_own(tab):
    tab._param_form.put_seeds({"seed": 42}, is_random=False)
    tab._how_many.set_how_many(2)
    requested = []
    tab.generate_requested.connect(lambda wf, batch: requested.append(batch))

    tab._on_generate()

    (batch,) = requested
    seeds = [params["seed"] for params in batch]
    assert seeds[0] == 42
    assert len(set(seeds)) == 2
    assert tab._param_form.seed_is_random() is True


def test_generate_refuses_an_unpaired_parenthesis_and_says_to_resolve_it(tab):
    requested = []
    tab.generate_requested.connect(lambda wf, batch: requested.append(batch))
    tab._param_form.set_values({"positive_prompt": "a (wizard", "seed": 42})

    tab._generate_btn.click()

    assert requested == []
    assert tab._generate_btn.text() == "Resolve parentheses first"
    assert tab._param_form.get_values()["seed"] == 42

    tab._param_form.set_values({"positive_prompt": "a (wizard)"})
    tab._generate_btn.click()
    assert len(requested) == 1


def test_generate_refuses_an_unpaired_parenthesis_in_the_negative_prompt_too(tab):
    requested = []
    tab.generate_requested.connect(lambda wf, batch: requested.append(batch))
    tab._param_form.set_values({"negative_prompt": "blurry)"})

    tab._generate_btn.click()

    assert requested == []


@pytest.mark.parametrize(("prompt", "says"), [
    ("a, b, a", "Resolve duplicates first"),
    ("a (b:high)", "Resolve bad numbers first"),
])
def test_generate_refuses_the_other_problems_it_highlights_and_says_which(tab, prompt, says):
    requested = []
    tab.generate_requested.connect(lambda wf, batch: requested.append(batch))
    tab._param_form.set_values({"positive_prompt": prompt})

    tab._generate_btn.click()

    assert requested == []
    assert tab._generate_btn.text() == says


def _press_in_the_popup(monkeypatch, caption):
    asked = []

    def press(box):
        asked.append(box.text())
        next(button for button in box.buttons() if button.text() == caption).click()

    monkeypatch.setattr(QMessageBox, "exec", press)
    return asked


@pytest.fixture
def prompt_read_as_plain_text(monkeypatch):
    monkeypatch.setattr(generate_tab_module, "prompt_readings", lambda _workflow, _values: {
        "positive_prompt": word_reading(76, CUT_OFF),
        "negative_prompt": word_reading(76, READ_IN_PIECES),
    })


def test_generate_offers_to_remove_emphasis_when_that_is_the_only_problem(tab, prompt_read_as_plain_text, monkeypatch):
    requested = []
    tab.generate_requested.connect(lambda wf, batch: requested.append(batch))
    asked = _press_in_the_popup(monkeypatch, "Remove emphasis")
    tab._param_form.set_values({"positive_prompt": "(a:1.2), ((b)), c"})

    tab._generate_btn.click()

    assert asked == ["This model reads parentheses and numbers as plain text, "
                     "so they add no strength."]
    assert tab._param_form.get_values()["positive_prompt"] == "a, b, c"
    assert requested == []
    assert tab._generate_btn.text() == "Generate"


def test_cancel_in_the_emphasis_popup_leaves_the_prompts_as_they_were(tab, prompt_read_as_plain_text, monkeypatch):
    requested = []
    tab.generate_requested.connect(lambda wf, batch: requested.append(batch))
    _press_in_the_popup(monkeypatch, "Cancel")
    tab._param_form.set_values({"positive_prompt": "(a:1.2), c"})

    tab._generate_btn.click()

    assert tab._param_form.get_values()["positive_prompt"] == "(a:1.2), c"
    assert requested == []


def test_generate_goes_ahead_once_the_emphasis_is_removed(tab, prompt_read_as_plain_text, monkeypatch):
    requested = []
    tab.generate_requested.connect(lambda wf, batch: requested.append(batch))
    _press_in_the_popup(monkeypatch, "Remove emphasis")
    tab._param_form.set_values({"positive_prompt": "(a:1.2), c"})

    tab._generate_btn.click()
    tab._generate_btn.click()

    assert len(requested) == 1


@pytest.mark.parametrize(("prompt", "says"), [
    ("(a), (b", "Resolve parentheses first"),
    ("(a), b:high)", "Resolve parentheses first"),
    ("(a), b, b", "Resolve unread emphasis first"),
])
def test_emphasis_beside_another_problem_gets_no_popup(tab, prompt_read_as_plain_text, prompt, says):
    tab._param_form.set_values({"positive_prompt": prompt})

    tab._generate_btn.click()

    assert tab._param_form.get_values()["positive_prompt"] == prompt
    assert tab._generate_btn.text() == says


def test_removing_emphasis_leaves_alone_a_prompt_whose_model_reads_it(tab, prompt_read_as_plain_text, monkeypatch):
    _press_in_the_popup(monkeypatch, "Remove emphasis")
    tab._param_form.set_values({"positive_prompt": "(a:1.2)", "negative_prompt": "(b:1.2)"})

    tab._generate_btn.click()

    values = tab._param_form.get_values()
    assert (values["positive_prompt"], values["negative_prompt"]) == ("a", "(b:1.2)")


def _yellow_words(field) -> list[str]:
    text = field.toPlainText()
    block = field.document().firstBlock()
    found = []
    while block.isValid():
        found += [text[block.position() + span.start:block.position() + span.start + span.length]
                  for span in block.layout().formats()
                  if span.format.background().color() == YELLOW]
        block = block.next()
    return found


def _prompt_box(tab, key):
    (box,) = tab._param_form._widgets[key].boxes()
    return box


@pytest.mark.parametrize(("positive", "negative"), [
    ("red cat, a dog", "blurry, red cat"),
    ("(Red Cat:1.2), a dog", "blurry, red cat"),
])
def test_generate_refuses_a_term_in_both_prompts_and_highlights_it_in_each(
        tab, positive, negative):
    requested = []
    tab.generate_requested.connect(lambda wf, batch: requested.append(batch))

    tab._param_form.set_values({"positive_prompt": positive, "negative_prompt": negative})
    tab._generate_btn.click()

    assert requested == []
    assert tab._generate_btn.text() == "Resolve prompt conflicts first"
    assert len(_yellow_words(_prompt_box(tab, "positive_prompt"))) == 1
    assert _yellow_words(_prompt_box(tab, "negative_prompt")) == ["red cat"]


def test_generate_goes_ahead_once_a_term_has_left_one_of_the_two_prompts(tab):
    requested = []
    tab.generate_requested.connect(lambda wf, batch: requested.append(batch))
    tab._param_form.set_values({"positive_prompt": "red cat", "negative_prompt": "red cat"})

    _prompt_box(tab, "negative_prompt").setPlainText("blurry")
    tab._generate_btn.click()

    assert len(requested) == 1
    assert _yellow_words(_prompt_box(tab, "positive_prompt")) == []


def _generate_color(tab):
    button = tab._generate_btn
    return button.grab().toImage().pixelColor(4, button.height() // 2)


def test_generate_is_yellow_while_it_says_what_to_resolve_and_then_goes_back(app_chrome, tab):
    tab.resize(900, 900)
    tab.show()
    resting = _generate_color(tab)
    tab._param_form.set_values({"positive_prompt": "a, b, a"})

    tab._generate_btn.click()
    assert _generate_color(tab) == YELLOW

    tab._generate_btn._guard_timer.timeout.emit()
    assert _generate_color(tab) == resting != YELLOW


def test_generate_emits_generate_requested_with_workflow_and_params(tab):
    tab._param_form.set_values({"positive_prompt": "a wizard", "seed": 42})
    requested = []
    tab.generate_requested.connect(lambda wf, batch: requested.append((wf, batch)))

    tab._on_generate()

    assert len(requested) == 1
    workflow_name, (params,) = requested[0]
    assert workflow_name == "sdxl_t2i"
    assert params["positive_prompt"] == "a wizard"
    assert params["seed"] == 42
    assert tab._db.list_generations() == []


def test_generate_sends_the_random_seed_on_show_and_then_shows_the_next_one(tab):
    shown = tab._param_form.get_values()["seed"]
    assert tab._param_form.seed_is_random() is True
    requested = []
    tab.generate_requested.connect(lambda wf, batch: requested.extend(batch))

    tab._on_generate()

    assert requested[0]["seed"] == shown
    assert tab._param_form.get_values()["seed"] != shown
    assert tab._param_form.seed_is_random() is True


def test_a_tab_with_no_image_to_start_from_grays_generate_and_says_why(qtbot, tmp_path):
    tab = GenerateTab(ComfyUIClient(folders=SUITE_FOLDERS), Database(tmp_path / "t.db"))
    qtbot.addWidget(tab)

    tab.prefill("image_enhance", WORKFLOW_REGISTRY["image_enhance"].default_params())
    qtbot.waitUntil(lambda: not tab._caption_timer.isActive())

    assert not tab._generate_btn.isEnabled()
    assert tab._generate_btn.toolTip() == "Nothing to start from — pick an Image first"


def test_picking_the_image_to_start_from_lights_generate(qtbot, tmp_path):
    tab = GenerateTab(ComfyUIClient(folders=SUITE_FOLDERS), Database(tmp_path / "t.db"))
    qtbot.addWidget(tab)
    tab.prefill("image_enhance", WORKFLOW_REGISTRY["image_enhance"].default_params())

    tab._param_form._widgets["input_image"].set_item("picked.png")

    assert tab._generate_btn.isEnabled()
    qtbot.waitUntil(lambda: not tab._caption_timer.isActive())
    assert tab._generate_btn.toolTip() == ""


def test_a_tab_opened_on_a_video_that_names_its_start_image_can_generate(saved_panel):
    tab, db = saved_panel

    tab.show_saved_generation(_video_row(db, input_image="frame.png [output]"), [])

    assert tab._generate_btn.isEnabled()


def _start_image_tab(qtbot, tmp_path, monkeypatch):
    output_dir = tmp_path / "output"
    (output_dir / "image").mkdir(parents=True)
    Image.new("RGB", (8, 8), (10, 20, 30)).save(output_dir / "image" / "sdxl_img1.png")
    monkeypatch.setattr(generate_tab_module, "OUTPUT_PLACES", OutputPlaces.in_one_folder(output_dir))
    db = Database(tmp_path / "t.db")
    tab = GenerateTab(MagicMock(), db)
    qtbot.addWidget(tab)
    tab._workflow_dropdown.setCurrentIndex(_dropdown_index(tab, "wan22_i2v"))
    return tab, db, tab._param_form._widgets["input_image"]


def test_an_image_let_go_over_the_start_image_shows_there_by_its_name(qtbot, tmp_path,
                                                                     monkeypatch):
    tab, db, start_image = _start_image_tab(qtbot, tmp_path, monkeypatch)
    thumbnail = tmp_path / "thumb.png"
    Image.new("RGB", (8, 8)).save(thumbnail)
    row = _image_row(db, filename="sdxl_img1.png")
    db.update_generation("img1", thumbnail_path=str(thumbnail))
    name = _named(tab, row)

    drops.let_go_over(start_image, "img1")

    assert start_image._caption.text() == name
    assert not start_image._label.pixmap().isNull()


def test_a_video_let_go_over_the_start_image_gives_it_the_image_it_was_made_from(
        qtbot, tmp_path, monkeypatch):
    _panel, db, start_image = _start_image_tab(qtbot, tmp_path, monkeypatch)
    _image_row(db, filename="sdxl_img1.png")
    _video_row(db, input_image="image/sdxl_img1.png [output]")

    drops.let_go_over(start_image, "vid1")

    assert start_image.current_id() == "image/sdxl_img1.png [output]"


def test_a_video_made_from_an_image_the_gallery_lacks_is_turned_away(qtbot, tmp_path,
                                                                      monkeypatch):
    _panel, db, start_image = _start_image_tab(qtbot, tmp_path, monkeypatch)
    _video_row(db, input_image="elsewhere.png")

    taken = drops.let_go_over(start_image, "vid1")

    assert not taken.isAccepted()
    assert start_image.current_id() is None


def test_the_start_image_lights_while_an_image_it_would_take_is_dragged(qtbot, tmp_path,
                                                                         monkeypatch):
    _panel, db, start_image = _start_image_tab(qtbot, tmp_path, monkeypatch)
    _image_row(db)
    _video_row(db, "vid1", input_image="image/sdxl_img1.png [output]")
    _video_row(db, "vid2", input_image="elsewhere.png")
    lit = []

    for dragged in ("img1", "vid1", "vid2"):
        mime = generation_mime(dragged)
        under_way.started.emit(mime, None)
        lit.append(start_image._label.property(LIT))
        under_way.ended.emit()

    assert lit == [True, True, False]
    assert start_image._label.property(LIT) is False


def test_an_image_let_go_anywhere_on_the_tab_becomes_its_start_image(qtbot, tmp_path,
                                                                     monkeypatch):
    tab, db, start_image = _start_image_tab(qtbot, tmp_path, monkeypatch)
    _image_row(db, filename="sdxl_img1.png")

    taken = drops.let_go_over(tab._workflow_dropdown, "img1")

    assert taken.isAccepted()
    assert start_image.current_id() == "image/sdxl_img1.png [output]"


def test_an_image_let_go_on_settings_with_no_image_box_is_turned_away(tab):
    _image_row(tab._db)

    assert not drops.let_go_over(tab._workflow_dropdown, "img1").isAccepted()


def test_a_video_let_go_anywhere_on_the_tab_fills_every_box_it_lends_something(
        qtbot, tmp_path, monkeypatch):
    tab, db, _start_image = _start_image_tab(qtbot, tmp_path, monkeypatch)
    tab._workflow_dropdown.setCurrentIndex(_dropdown_index(tab, "wan22_animate"))
    _image_row(db, filename="sdxl_img1.png")
    _video_row(db, input_image="image/sdxl_img1.png [output]")

    taken = drops.let_go_over(tab._workflow_dropdown, "vid1")

    values = tab._param_form.get_values()
    assert taken.isAccepted()
    assert values["input_image"] == "image/sdxl_img1.png [output]"
    assert values["video"] == str(generate_tab_module.OUTPUT_PLACES.file("video/vid1.mp4"))


def test_a_start_image_from_outside_the_gallery_is_named_by_its_file_and_goes_nowhere(
        qtbot, tmp_path, monkeypatch):
    tab, _db, start_image = _start_image_tab(qtbot, tmp_path, monkeypatch)
    outside = tmp_path / "picked.png"
    Image.new("RGB", (8, 8)).save(outside)
    tab._param_form.set_values({"input_image": str(outside)})
    went = []
    tab.link_clicked.connect(went.append)

    qtbot.mouseClick(start_image, Qt.MouseButton.LeftButton)

    assert went == []
    assert start_image._caption.text() == "picked.png"
    assert start_image.toolTip() == "picked.png"


def test_a_fresh_tab_generates_nothing_until_its_start_image_is_picked(qtbot, tmp_path):
    tab = GenerateTab(MagicMock(), Database(tmp_path / "t.db"))
    qtbot.addWidget(tab)
    tab._workflow_dropdown.setCurrentIndex(_dropdown_index(tab, "wan22_i2v"))
    requested = []
    tab.generate_requested.connect(lambda wf, batch: requested.append(wf))

    tab._on_generate()

    assert requested == []
    assert tab._db.list_generations() == []
    assert not tab._generate_btn.isEnabled()
    assert tab._generate_btn.toolTip() == "Nothing to start from — pick a Start Image first"


def test_workflow_picker_hides_machinery_workflows(qtbot, tmp_path):
    tab = GenerateTab(ComfyUIClient(folders=SUITE_FOLDERS), Database(tmp_path / "t.db"))
    qtbot.addWidget(tab)
    dropdown = tab._workflow_dropdown
    keys = {dropdown.itemData(i) for i in range(dropdown.count())}
    assert "image_enhance" not in keys
    assert "sdxl_t2i" in keys

    tab.prefill("image_enhance", WORKFLOW_REGISTRY["image_enhance"].default_params())
    assert dropdown.currentData() == "image_enhance"


def _listed_workflows(tab):
    dropdown = tab._workflow_dropdown
    return [dropdown.itemData(i) for i in range(dropdown.count())]


def _offered(kind):
    return [wf.name for wf in offered_workflows(makes=kind)]


def test_a_new_generation_tab_lists_the_workflows_of_both_kinds(blank_panel):
    assert set(_listed_workflows(blank_panel)) == {
        *_offered(MediaType.IMAGE), *_offered(MediaType.VIDEO)}


@pytest.mark.parametrize(("picked", "kind"), [("wan22_i2v", MediaType.VIDEO),
                                          ("sdxl_t2i", MediaType.IMAGE)])
def test_a_workflow_picked_in_a_new_generation_tab_leaves_only_its_kind_listed(
        blank_panel, qtbot, picked, kind):
    dropdown = blank_panel._workflow_dropdown
    dropdown.showPopup()
    view = dropdown.view()
    row = dropdown.model().index(_dropdown_index(blank_panel, picked), 0)

    qtbot.mouseClick(view.viewport(), Qt.MouseButton.LeftButton,
                     pos=view.visualRect(row).center())

    assert dropdown.currentData() == picked
    assert _listed_workflows(blank_panel) == _offered(kind)


def test_a_tab_showing_a_video_lists_only_the_video_workflows(saved_panel):
    tab, db = saved_panel

    tab.show_saved_generation(_video_row(db), [])

    assert _listed_workflows(tab) == _offered(MediaType.VIDEO)


def test_a_tab_that_showed_a_video_lists_only_the_image_workflows_once_it_shows_an_image(
        saved_panel):
    tab, db = saved_panel
    tab.show_saved_generation(_video_row(db), [])
    image = _image_row(db)

    tab.show_saved_generation(image, [image])

    assert _listed_workflows(tab) == _offered(MediaType.IMAGE)
    assert tab._workflow_dropdown.currentData() == "sdxl_t2i"


def _wiz_params():
    return dict(WORKFLOW_REGISTRY["sdxl_t2i"].default_params(), positive_prompt="a wizard")


_SDXL_VERSION = WORKFLOW_REGISTRY["sdxl_t2i"].version


def test_recent_matching_row_finds_only_the_folders_own(qtbot, tmp_path):
    db = Database(tmp_path / "t.db")
    db.insert_generation(NewGeneration(
        prompt_id="wiz", workflow_name="sdxl_t2i", workflow_version=_SDXL_VERSION,
        positive_prompt="a wizard", params_json=json.dumps(_wiz_params()), workflow_json="{}",
    ))
    db.insert_generation(NewGeneration(
        prompt_id="drg", workflow_name="sdxl_t2i", workflow_version=_SDXL_VERSION,
        positive_prompt="a dragon",
        params_json=json.dumps(dict(WORKFLOW_REGISTRY["sdxl_t2i"].default_params(),
                                    positive_prompt="a dragon")),
        workflow_json="{}",
    ))
    tab = GenerateTab(ComfyUIClient(folders=SUITE_FOLDERS), db)
    qtbot.addWidget(tab)
    tab.prefill("sdxl_t2i", _wiz_params())
    assert tab._recent_matching_row()["prompt_id"] == "wiz"


def test_prefill_shows_the_recent_match_in_the_preview(qtbot, tmp_path, monkeypatch):
    db = Database(tmp_path / "t.db")
    db.insert_generation(NewGeneration(
        prompt_id="g1", workflow_name="sdxl_t2i", workflow_version=_SDXL_VERSION,
        positive_prompt="a wizard", params_json=json.dumps(_wiz_params()), workflow_json="{}",
    ))
    monkeypatch.setattr(generate_tab_module, "resolve_preview", lambda row, out: ("wiz.png", "image"))
    tab = GenerateTab(ComfyUIClient(folders=SUITE_FOLDERS), db)
    qtbot.addWidget(tab)
    shown = []
    monkeypatch.setattr(tab._viewport, "show_media",
                        lambda path, mt, generation: shown.append((path, mt, generation)))

    tab.prefill("sdxl_t2i", _wiz_params())

    assert shown[-1] == ("wiz.png", "image", "g1")


def test_idle_panel_with_no_matching_generation_stays_blank(qtbot, tmp_path):
    tab = GenerateTab(ComfyUIClient(folders=SUITE_FOLDERS), Database(tmp_path / "t.db"))
    qtbot.addWidget(tab)
    tab.show_recent_preview()
    assert tab._viewport._media is None
    assert tab._viewport._generation is None


def test_autoshowing_a_recent_result_arms_the_preview_drag(qtbot, tmp_path, monkeypatch):
    db = Database(tmp_path / "t.db")
    db.insert_generation(NewGeneration(
        prompt_id="g1", workflow_name="sdxl_t2i", workflow_version=_SDXL_VERSION,
        positive_prompt="a wizard", params_json=json.dumps(_wiz_params()), workflow_json="{}",
    ))
    monkeypatch.setattr(generate_tab_module, "resolve_preview", lambda row, out: ("wiz.png", "image"))
    tab = GenerateTab(ComfyUIClient(folders=SUITE_FOLDERS), db)
    qtbot.addWidget(tab)
    tab.prefill("sdxl_t2i", _wiz_params())

    assert tab._viewport._generation == "g1"


def test_an_image_the_tab_puts_up_itself_is_announced_like_a_clicked_one(
        qtbot, tmp_path, monkeypatch):
    db = Database(tmp_path / "t.db")
    db.insert_generation(NewGeneration(
        prompt_id="g1", workflow_name="sdxl_t2i", workflow_version=_SDXL_VERSION,
        positive_prompt="a wizard", params_json=json.dumps(_wiz_params()), workflow_json="{}",
    ))
    monkeypatch.setattr(generate_tab_module, "resolve_preview", lambda row, out: ("wiz.png", "image"))
    tab = GenerateTab(ComfyUIClient(folders=SUITE_FOLDERS), db)
    qtbot.addWidget(tab)
    announced = []
    tab.displayed_changed.connect(lambda: announced.append(tab.displayed_row()))

    tab.prefill("sdxl_t2i", _wiz_params())

    assert [row["prompt_id"] for row in announced if row][-1:] == ["g1"]


def test_current_config_does_not_randomize_and_reports_random_flag(tab):
    snap1 = tab.current_config()
    snap2 = tab.current_config()
    assert snap1.workflow_name == "sdxl_t2i"
    assert snap1.seed_is_random is True
    assert snap1.params["seed"] == snap2.params["seed"]

    tab.prefill("sdxl_t2i", {"seed": 99})
    snap3 = tab.current_config()
    assert snap3.seed_is_random is False
    assert snap3.params["seed"] == 99


def test_prefill_selects_workflow_and_sets_values(tab):
    tab.prefill("wan22_i2v", {"positive_prompt": "a fox"})
    assert tab._workflow_dropdown.currentData() == "wan22_i2v"
    assert tab._param_form.get_values()["positive_prompt"] == "a fox"


def test_prefilling_a_clip_keeps_random_and_shows_a_fresh_take_of_its_seeds(tab):
    tab.prefill("wan22_i2v", {"noise_seed": 11, "audio_seed": 33})

    shown = tab._param_form.get_values()
    assert tab.current_config().seed_is_random is True
    assert shown["noise_seed"] != 11
    assert shown["audio_seed"] != 33


def test_a_press_that_would_remake_the_item_on_show_draws_its_first_seed_fresh(saved_panel):
    tab, db = saved_panel
    tab.show_saved_generation(
        _video_row(db, input_image="frame.png", noise_seed=22, audio_seed=33), [])
    for key in ("noise_seed", "audio_seed"):
        tab._param_form._randomize_checks[key].click()
    tab._how_many.set_how_many(2)
    requested = []
    tab.generate_requested.connect(lambda wf, batch: requested.append(batch))

    tab._on_generate()

    (batch,) = requested
    assert 22 not in {params["noise_seed"] for params in batch}


def test_unticking_random_on_a_clip_on_display_puts_its_own_seed_back(saved_panel):
    tab, db = saved_panel
    tab.show_saved_generation(_video_row(db, input_image="frame.png [output]", noise_seed=22), [])

    tab._param_form._randomize_checks["noise_seed"].click()

    assert tab._param_form.get_values()["noise_seed"] == 22


def test_a_tab_showing_a_still_wears_its_thumbnail_in_the_seed_field(saved_panel, tmp_path):
    tab, db = saved_panel
    thumbnail = tmp_path / "made.png"
    red = QPixmap(40, 40)
    red.fill(QColor("red"))
    red.save(str(thumbnail))
    _image_row(db, "img1")
    db.update_generation("img1", thumbnail_path=str(thumbnail))

    tab.show_saved_generation(db.get_generation("img1"), [])

    image = tab._param_form._widgets["seed"]._thumbnail.pixmap().toImage()
    assert image.pixelColor(image.width() // 2, image.height() // 2) == QColor("red")


def test_a_random_seed_stays_random_across_a_workflow_switch(tab):
    tab._workflow_dropdown.setCurrentIndex(_dropdown_index(tab, "flux_t2i_upscaled"))

    assert tab._param_form.seed_is_random() is True


def test_a_prompt_carried_from_a_workflow_that_reads_it_whole_flows_into_boxes_of_whole_words(
        tab, monkeypatch, tmp_path):
    monkeypatch.setattr(config, "COMFYUI_DIR", tmp_path / "ComfyUI")
    clip_reader(tmp_path / "ComfyUI")
    cats = " ".join(["cat"] * 74)
    tab._workflow_dropdown.setCurrentIndex(_dropdown_index(tab, "flux_t2i_upscaled"))
    tab._param_form.set_values({"positive_prompt": f"{cats} abcdefgh"})

    tab._workflow_dropdown.setCurrentIndex(_dropdown_index(tab, "sdxl_t2i"))

    boxes = tab._param_form._widgets["positive_prompt"].boxes()
    assert [diff_text.live_text(box) for box in boxes] == [cats, "abcdefgh"]
    assert tab._param_form.get_values()["positive_prompt"] == f"{cats}{BOX_BREAK}abcdefgh"


def test_a_prompt_in_boxes_carried_to_a_workflow_that_reads_it_whole_is_read_whole(
        tab, monkeypatch, tmp_path):
    monkeypatch.setattr(config, "COMFYUI_DIR", tmp_path / "ComfyUI")
    word_reader(tmp_path / "ComfyUI" / "comfy" / "text_encoders" / "t5_tokenizer"
                / "tokenizer.json")
    tab._param_form.set_values({"positive_prompt": f"a lantern{BOX_BREAK}on a jetty"})

    tab._workflow_dropdown.setCurrentIndex(_dropdown_index(tab, "flux_t2i_upscaled"))

    assert tab._param_form.get_values()["positive_prompt"] == "a lantern on a jetty"


def test_a_pinned_seed_stays_pinned_across_a_switch_between_video_workflows(tab):
    tab.prefill("wan22_flf2v_loop", {})
    tab._param_form.put_seeds({"noise_seed": 99}, is_random=False)

    tab._workflow_dropdown.setCurrentIndex(_dropdown_index(tab, "wan22_i2v"))

    assert tab._param_form.get_values()["noise_seed"] == 99
    assert "noise_seed" not in tab._param_form.random_seed_keys()


def test_restore_config_reapplies_workflow_params_and_random_seed(tab):
    snap = ConfigSnapshot("wan22_i2v", {"positive_prompt": "a fox"}, seed_is_random=True)
    tab.restore_config(snap)
    assert tab._workflow_dropdown.currentData() == "wan22_i2v"
    assert tab._param_form.get_values()["positive_prompt"] == "a fox"
    assert tab._param_form.seed_is_random() is True


def test_a_random_tab_comes_back_showing_the_seed_it_showed(tab):
    tab.restore_config(ConfigSnapshot("wan22_i2v", {"noise_seed": 77}, seed_is_random=True))

    assert tab._param_form.get_values()["noise_seed"] == 77
    assert tab._param_form.seed_is_random() is True


def test_restore_config_pins_concrete_seed_when_not_random(tab):
    tab.restore_config(ConfigSnapshot("sdxl_t2i", {"seed": 99}, seed_is_random=False))
    snap = tab.current_config()
    assert snap.seed_is_random is False
    assert snap.params["seed"] == 99


def test_a_fresh_panel_picks_no_workflow(blank_panel):
    assert blank_panel._workflow_dropdown.currentIndex() == -1, (
        "the resting tab asks which workflow to run, rather than presenting whichever is registered "
        "first as a choice already made")
    assert blank_panel._workflow_dropdown.currentData() is None
    assert blank_panel._workflow_dropdown.placeholderText()


def test_a_fresh_panel_lays_out_nothing_the_workflow_decides(blank_panel):
    assert blank_panel._param_form is None
    assert blank_panel._estimate_label.isHidden()


def test_a_fresh_panel_cannot_generate(blank_panel):
    assert blank_panel._generate_btn.isEnabled() is False


def test_picking_a_workflow_fills_in_everything_below(blank_panel):
    blank_panel._workflow_dropdown.setCurrentIndex(_dropdown_index(blank_panel, "sdxl_t2i"))
    assert blank_panel._param_form is not None
    assert not blank_panel._estimate_label.isHidden()
    assert blank_panel._generate_btn.isEnabled() is True


def test_a_fresh_panel_is_blank_and_a_used_one_is_not(blank_panel):
    assert blank_panel.is_blank() is True
    blank_panel._workflow_dropdown.setCurrentIndex(_dropdown_index(blank_panel, "sdxl_t2i"))
    assert blank_panel.is_blank() is False


def test_a_fresh_panel_shows_the_previews_placeholder_not_a_black_pane(blank_panel):
    assert blank_panel._displayed_row is None


def test_a_fresh_panel_names_itself_for_what_it_is(blank_panel):
    assert blank_panel.title() == "New generation", (
        "unknown would read as a workflow the app failed to recognize, not a question nobody has "
        "answered yet")


def test_generate_on_a_workflowless_panel_asks_for_nothing(blank_panel):
    fired = []
    blank_panel.generate_requested.connect(lambda *a: fired.append(a))
    blank_panel._on_generate()
    assert fired == []


def _folder_name(tab):
    return gallery.config_folder_name(*tab.workflow_and_signature(),
                                      tab._db.folder_meta_map())


def test_a_config_with_no_result_is_named_by_its_folder(tab):
    assert tab.title() == _folder_name(tab)
    assert tab.title() != "New generation"


def test_a_folder_the_user_named_gives_the_tab_that_name(tab):
    tab._db.upsert_folder_meta(settings_key("image", *tab.workflow_and_signature()),
                                 custom_name="Wizards", favorite=False, level=None,
                                 ref_prompt_id=None)

    assert tab.title() == "Wizards"


def _named(tab, row) -> str:
    tab._names.take([row], [], {})
    return f"{folder_id(settings_folder_key(row))} 000"


def test_a_displayed_item_names_the_tab_by_its_name_not_its_file(tab):
    row = _image_row(tab._db, filename="sdxl_img1.png")
    name = _named(tab, row)
    tab._viewport.show_media = MagicMock()

    tab.show_saved_generation(row, [row])

    assert tab.title() == name, (
        "named after what it shows rather than after its settings, so the row of tabs reads as the "
        "things that are open")


def test_title_changed_when_the_shown_item_changes(tab):
    row = _image_row(tab._db, filename="sdxl_img1.png")
    name = _named(tab, row)
    tab._viewport.show_media = MagicMock()
    titles = []
    tab.title_changed.connect(titles.append)

    tab.show_saved_generation(row, [row])

    assert titles
    assert titles[-1] == name


def test_the_mark_is_the_shown_items_own_thumbnail(tab, tmp_path):
    pixmap = QPixmap(4, 4)
    pixmap.fill(Qt.GlobalColor.red)
    thumb = tmp_path / "thumb.png"
    pixmap.save(str(thumb))
    row = dict(_image_row(tab._db), thumbnail_path=str(thumb))
    tab._viewport.show_media = MagicMock()

    tab.show_saved_generation(row, [row])

    assert tab.tab_icon().availableSizes() == [QSize(4, 4)]


def test_the_mark_falls_back_to_what_the_config_makes(tab):
    assert tab.tab_icon().cacheKey() == icons.media_type_icon(MediaType.IMAGE).cacheKey()


def test_a_tab_with_no_workflow_yet_wears_no_mark(blank_panel):
    assert blank_panel.tab_icon().isNull(), (
        "nothing is known yet, and a mark guessing at a workflow would be the tab's most confident claim")


class SpyDB:
    def __init__(self, durations=None):
        self._durations = durations or []

    def list_trashed(self):
        return []

    def recent_durations(self, workflow_name, limit=10):
        return list(self._durations)

    def list_generations(self):
        return []

    def get_generation(self, prompt_id):
        return None

    def get_request(self, prompt_id):
        return None

    def requests_about(self, prompt_id):
        return []

    def library_version(self):
        return 0

    def folder_meta_map(self):
        return {}


def _spy_panel(qtbot, db):
    tab = GenerateTab(ComfyUIClient(folders=SUITE_FOLDERS), db)
    qtbot.addWidget(tab)
    tab._workflow_dropdown.setCurrentIndex(_dropdown_index(tab, "sdxl_t2i"))
    return tab


def test_estimate_label_reflects_recent_durations(qtbot):
    tab = _spy_panel(qtbot, SpyDB(durations=[700.0, 724.0, 800.0]))
    assert tab._estimate_label.text() == "~12 min (based on 3 runs)"


def test_estimate_label_when_no_history(qtbot):
    tab = _spy_panel(qtbot, SpyDB(durations=[]))
    assert tab._estimate_label.text() == "No timing data yet"


def test_the_two_parts_match_a_stored_generation_of_the_same_settings(tab):
    full = dict(WORKFLOW_REGISTRY["sdxl_t2i"].default_params())
    full["positive_prompt"] = "a cat"
    tab.prefill("sdxl_t2i", full)
    workflow, signature = tab.workflow_and_signature()
    assert workflow == "sdxl_t2i"
    assert signature == gallery.settings_signature("sdxl_t2i", json.dumps({**full, "seed": 999}))
    assert signature != gallery.settings_signature("sdxl_t2i", json.dumps({**full, "steps": 7}))


def test_a_config_that_has_generated_has_a_folder_to_go_to(qtbot, tmp_path):
    db = Database(tmp_path / "t.db")
    params = dict(WORKFLOW_REGISTRY["sdxl_t2i"].default_params(),
                  positive_prompt="a wizard")
    db.insert_generation(NewGeneration(
        prompt_id="g1", workflow_name="sdxl_t2i", workflow_version=_SDXL_VERSION,
        positive_prompt="a wizard", params_json=json.dumps(params), workflow_json="{}",
    ))
    tab = GenerateTab(ComfyUIClient(folders=SUITE_FOLDERS), db)
    qtbot.addWidget(tab)
    tab.prefill("sdxl_t2i", params)

    row = db.get_generation("g1")
    assert tab.settings_folder_key() == gallery.settings_folder_key(
        row, gallery.build_image_config_index([row]))


def test_a_config_that_has_generated_nothing_has_no_folder_yet(tab):
    assert tab.settings_folder_key() is None


def test_a_panel_still_on_the_picker_has_no_folder(blank_panel):
    assert blank_panel.settings_folder_key() is None


def _image_being_made(db, prompt_id="img1", prompt="a cat", **settings):
    params = dict(WORKFLOW_REGISTRY["sdxl_t2i"].default_params(),
                  positive_prompt=prompt, seed=1, **settings)
    db.insert_generation(NewGeneration(
        prompt_id=prompt_id, workflow_name="sdxl_t2i", workflow_version="v002",
        positive_prompt=prompt, seed=1,
        params_json=json.dumps(params), workflow_json="{}",
    ))
    db.update_generation(prompt_id, status="running")
    return db.get_generation(prompt_id)


def _image_row(db, prompt_id="img1", prompt="a cat", filename="sdxl_img1.png", **settings):
    _image_being_made(db, prompt_id, prompt, **settings)
    db.update_generation(prompt_id, status="completed",
                         output_files=json.dumps([{"filename": filename, "subfolder": "image"}]))
    return db.get_generation(prompt_id)


def _video_row(db, prompt_id="vid1", input_image=None, *, workflow_name="wan22_i2v",
               **seeds):
    params = {"positive_prompt": "dance", "seed": 5, **seeds}
    if input_image is not None:
        params["input_image"] = input_image
    db.insert_generation(NewGeneration(
        prompt_id=prompt_id, workflow_name=workflow_name, workflow_version="v002",
        positive_prompt="dance", seed=5,
        params_json=json.dumps(params), workflow_json="{}",
    ))
    db.update_generation(prompt_id, status="completed",
                         output_files=json.dumps([{"filename": f"{prompt_id}.mp4", "subfolder": "video"}]))
    return db.get_generation(prompt_id)


@pytest.fixture
def saved_panel(qtbot, tmp_path, installed_models):
    db = Database(tmp_path / "t.db")
    tab = GenerateTab(ComfyUIClient(folders=SUITE_FOLDERS), db)
    qtbot.addWidget(tab)
    tab._workflow_dropdown.setCurrentIndex(_dropdown_index(tab, "sdxl_t2i"))
    tab._viewport.show_media = MagicMock()
    return tab, db


def _shown_metadata(tab):
    form = tab._metadata_section.form()
    return [form.itemAt(row, QFormLayout.ItemRole.LabelRole).widget().findChild(ElidingLabel).text()
            for row in range(form.rowCount())
            if form.isRowVisible(row) and form.itemAt(row, QFormLayout.ItemRole.LabelRole)]


def _metadata_texts(tab):
    return [lbl.text().replace("\u200b", "")
            for lbl in tab._metadata_section.findChildren(QLabel)]


def test_a_tab_showing_an_item_puts_its_name_on_the_name_line(qtbot, tmp_path):
    db = Database(tmp_path / "t.db")
    image = _image_row(db)
    names = ItemNames(db)
    names.take([image], [], {})
    tab = GenerateTab(ComfyUIClient(folders=SUITE_FOLDERS), db, views=TabViews(names=names))
    qtbot.addWidget(tab)
    tab._viewport.show_media = MagicMock()

    tab.show_saved_generation(image, [image])

    assert f"{folder_id(settings_folder_key(image))} 000" in _metadata_texts(tab)


def test_a_fresh_tab_shows_no_footer(saved_panel):
    tab, _db = saved_panel
    assert tab._displayed_row is None
    assert _shown_metadata(tab) == [TYPICAL_TIME]
    assert tab._versions.isHidden()
    assert tab._related._animations.isHidden()
    assert source_tile(tab._related).isHidden()
    assert tab._lane_button.isHidden()


def _enhanced_image_row(db, prompt_id="img1"):
    _image_row(db, prompt_id)
    return _fold_enhancement(db, prompt_id)


def _fold_enhancement(db, prompt_id="img1"):
    db.update_generation(
        prompt_id,
        output_files=json.dumps([
            {"filename": "image_enhance_00001_.png", "subfolder": "image"},
            {"filename": "sdxl_img1.png", "subfolder": "image"},
        ]),
        original_files=json.dumps([{"filename": "sdxl_img1.png", "subfolder": "image"}]),
        enhance_history=json.dumps([
            {"filename": "image_enhance_00001_.png",
             "params": {"enhance_scale": 2.0, "enhance_steps": 20,
                        "enhance_denoise": 0.15}},
        ]),
    )
    return db.get_generation(prompt_id)


def _version_rows(tab):
    return tab._versions._host.findChildren(_VersionRow)


def _row_texts(row):
    return [lbl.text().replace("\u200b", "") for lbl in row.findChildren(QLabel)]


def test_a_levels_facts_sit_one_gap_after_their_longest_key_as_a_field_after_its_label(saved_panel):
    tab, db = saved_panel
    image = _enhanced_image_row(db)
    tab.show_saved_generation(image, [image])
    tab.resize(480, 1400)
    tab.show()
    tab.layout().activate()
    facts = next(row for row in _version_rows(tab) if "Enhancement" in _row_texts(row))._facts
    lines = [line for line in range(1, facts.rowCount()) if facts.itemAtPosition(line, 1)]
    keys = [facts.itemAtPosition(line, 0).widget() for line in lines]
    values = [facts.itemAtPosition(line, 1).widget() for line in lines]
    longest = max(key.fontMetrics().horizontalAdvance(key.text()) for key in keys)

    assert {value.x() - (key.x() + longest) for key, value in zip(keys, values, strict=True)} == {GAP_MEDIUM}


def test_an_unenhanced_image_still_shows_its_original_and_the_add_tile(saved_panel):
    tab, db = saved_panel
    image = _image_row(db, "img1")
    tab.show_saved_generation(image, [image])
    assert not tab._versions.isHidden(), (
        "the list of versions has to be somewhere the user can already see before the first "
        "enhancement makes a second one, not least because an enhancement just launched "
        "replaces the list's only other content while it runs")
    (row,) = _version_rows(tab)
    assert "Original" in _row_texts(row)
    assert tab._versions._host.findChildren(_AddRow)


def _evolver_upscaled_video(db, monkeypatch, tmp_path, prompt_id="vid1"):
    output = tmp_path / "out"
    video = output / "video" / f"{prompt_id}.mp4"
    video.parent.mkdir(parents=True)
    video.write_bytes(b"video")
    os.utime(video, (1_000_000, 1_000_000))
    library = tmp_path / "upscaled_by_orientation"
    upscale = library / "portrait" / EVOLVER_SOURCE / f"{prompt_id}_topaz.mp4"
    upscale.parent.mkdir(parents=True)
    upscale.write_bytes(b"upscale")
    monkeypatch.setattr(generate_tab_module, "OUTPUT_PLACES", OutputPlaces.in_one_folder(output))
    monkeypatch.setattr(library_views, "KINO_UPSCALES_DIR", library)
    return _video_row(db, prompt_id), upscale


def test_a_video_evolver_upscaled_lists_the_upscale_over_the_video(saved_panel, monkeypatch,
                                                                    tmp_path):
    tab, db = saved_panel
    video, upscale = _evolver_upscaled_video(db, monkeypatch, tmp_path)

    tab.show_saved_generation(video, [])

    rows = _version_rows(tab)
    assert [row._title.text() for row in rows] == ["Evolved", "Original"]
    assert upscale.name in _row_texts(rows[0])
    assert _shown_metadata(tab) == [*SIDE_LABELS.values(), TYPICAL_TIME]


def test_picking_the_evolved_version_plays_it_in_the_preview(saved_panel, monkeypatch,
                                                             tmp_path):
    tab, db = saved_panel
    video, upscale = _evolver_upscaled_video(db, monkeypatch, tmp_path)
    tab.show_saved_generation(video, [])
    tab._viewport.show_media.reset_mock()

    tab._show_version(0)

    tab._viewport.show_media.assert_called_once_with(upscale, "video", "vid1")


def test_an_upscaled_videos_versions_have_no_trash_can(saved_panel, monkeypatch, tmp_path):
    tab, db = saved_panel
    video, _upscale = _evolver_upscaled_video(db, monkeypatch, tmp_path)

    tab.show_saved_generation(video, [])

    rows = _version_rows(tab)
    assert len(rows) == 2
    assert [row.findChild(QPushButton, "deleteButton") for row in rows] == [None, None], (
        "a video's versions are the video itself and the copy Evolver keeps, so they are not "
        "this list's to trash")


def test_an_enhanced_image_lists_its_levels_newest_first(saved_panel):
    tab, db = saved_panel
    image = _enhanced_image_row(db)
    tab.show_saved_generation(image, [image])

    assert not tab._versions.isHidden()
    rows = _version_rows(tab)
    first = " / ".join(t for t in _row_texts(rows[0]) if t and t != "—")
    assert first.startswith("Enhancement 1/1")
    assert "2x" in first
    assert "20 steps" in first
    assert "0.15 redraw" in first
    assert "Original" in _row_texts(rows[1])


def test_each_level_carries_its_own_file_row(saved_panel):
    tab, db = saved_panel
    image = _enhanced_image_row(db)
    tab.show_saved_generation(image, [image])

    rows = _version_rows(tab)
    assert "image/image_enhance_00001_.png" in _row_texts(rows[0])
    assert "image/sdxl_img1.png" in _row_texts(rows[1])
    assert [[b.objectName() for b in row.findChildren(QPushButton)] for row in rows] == [
        ["copyButton", "deleteButton", "revealButton"],
        ["copyButton", "revealButton"],
    ]
    for row in rows:
        assert "Created" in _row_texts(row)
    assert "File" not in _metadata_texts(tab)


def test_the_way_to_the_folder_is_one_button_in_the_row_with_generate(saved_panel):
    tab, db = saved_panel
    tab.set_folder_check(lambda row: True)
    image = _enhanced_image_row(db)

    tab.show_saved_generation(image, [image])

    buttons = tab.findChildren(QPushButton, "goToFolderButton")
    assert len(buttons) == 1, (
        "every version of an image is in the same folder, so going there is the image's act "
        "rather than any one version's")
    (button,) = buttons
    tab.resize(700, 1600)
    tab.show()
    QApplication.processEvents()
    body = tab._settings_scroll.widget()

    assert button.isVisibleTo(tab)
    assert button.mapTo(tab, QPoint(0, 0)).y() == tab._generate_pair.mapTo(tab, QPoint(0, 0)).y()
    assert button.mapTo(tab, QPoint(0, 0)).x() == body.mapTo(tab, QPoint(
        body.layout().contentsMargins().left(), 0)).x()
    for row in _version_rows(tab):
        assert "goToFolderButton" not in [b.objectName()
                                          for b in row.findChildren(QPushButton)]


def test_an_enhancement_in_flight_shows_in_the_strip(saved_panel):
    tab, db = saved_panel
    image = _image_row(db, "img1")
    tab.show_saved_generation(image, [image])
    assert not tab._versions._host.findChildren(_PendingRow)

    tab.set_pending_enhancement(RunningEnhancement("running", None, "2x · 20 steps · 0.15 redraw"))

    assert not tab._versions.isHidden()
    assert tab._versions._host.findChildren(_PendingRow)
    assert _version_rows(tab), (
        "the original stays beside the one being made: the base render is out and worth looking "
        "at while its enhancement is made")

    tab.set_pending_enhancement(None)
    assert not tab._versions._host.findChildren(_PendingRow)


def test_a_running_enhancement_streams_into_the_preview(saved_panel, tmp_path,
                                                        monkeypatch):
    tab, db = saved_panel
    output_dir = tmp_path / "out"
    (output_dir / "image").mkdir(parents=True)
    (output_dir / "image" / "sdxl_img1.png").write_bytes(b"x")
    monkeypatch.setattr(generate_tab_module, "OUTPUT_PLACES", OutputPlaces.in_one_folder(output_dir))

    image = _image_row(db, "img1")
    tab.show_saved_generation(image, [image])
    tab._viewport.show_frame = MagicMock()
    tab._viewport.show_media.reset_mock()

    tab.set_pending_enhancement(RunningEnhancement("running", b"\x89PNG-ish", "2x"))
    shown = tab._viewport.show_frame.call_args_list
    assert shown == [((b"\x89PNG-ish",), {"enhancing": True})], (
        "the preview at the top of the tab is where this app shows what is being made, and an "
        "enhancement of the image on display is being made")

    tab.set_pending_enhancement(None)
    tab._viewport.show_media.assert_called_once_with(
        output_dir / "image" / "sdxl_img1.png", "image", "img1"
    )


def test_picked_levels_are_deleted_by_filename(saved_panel):
    tab, db = saved_panel
    image = _enhanced_image_row(db)
    tab.show_saved_generation(image, [image])
    asked = []
    tab.versions_delete_requested.connect(lambda pid, names: asked.append((pid, names)))

    tab._versions.delete_requested.emit([0])

    assert asked == [("img1", ["image_enhance_00001_.png"])]


def test_picking_a_level_swaps_the_preview_without_changing_the_selection(saved_panel,
                                                                          tmp_path,
                                                                          monkeypatch):
    tab, db = saved_panel
    output_dir = tmp_path / "out"
    (output_dir / "image").mkdir(parents=True)
    for name in ("image_enhance_00001_.png", "sdxl_img1.png"):
        (output_dir / "image" / name).write_bytes(b"x")
    monkeypatch.setattr(generate_tab_module, "OUTPUT_PLACES", OutputPlaces.in_one_folder(output_dir))

    image = _enhanced_image_row(db)
    tab.show_saved_generation(image, [image])
    tab._viewport.show_media.reset_mock()

    tab._show_version(1)

    tab._viewport.show_media.assert_called_once_with(
        output_dir / "image" / "sdxl_img1.png", "image", "img1"
    )
    assert tab._displayed_row["prompt_id"] == "img1"


def test_an_arrow_after_a_level_is_clicked_puts_the_next_level_in_the_preview(
        saved_panel, qtbot, tmp_path, monkeypatch):
    tab, db = saved_panel
    output_dir = tmp_path / "out"
    (output_dir / "image").mkdir(parents=True)
    for name in ("image_enhance_00001_.png", "sdxl_img1.png"):
        (output_dir / "image" / name).write_bytes(b"x")
    monkeypatch.setattr(generate_tab_module, "OUTPUT_PLACES", OutputPlaces.in_one_folder(output_dir))
    image = _enhanced_image_row(db)
    tab.show_saved_generation(image, [image])
    newest = _version_rows(tab)[0]
    qtbot.mouseClick(newest, Qt.MouseButton.LeftButton)
    tab._viewport.show_media.reset_mock()

    qtbot.keyClick(newest, Qt.Key.Key_Down)

    tab._viewport.show_media.assert_called_once_with(
        output_dir / "image" / "sdxl_img1.png", "image", "img1"
    )


def test_up_onto_the_enhance_row_and_enter_asks_for_an_enhance_of_the_image(saved_panel, qtbot):
    tab, db = saved_panel
    image = _enhanced_image_row(db)
    tab.set_enhance_settings(gallery.EnhanceSettings(params={"enhance_scale": 3.0}))
    tab.show_saved_generation(image, [image])
    asked = []
    tab.enhance_requested.connect(asked.append)
    newest = _version_rows(tab)[0]
    qtbot.mouseClick(newest, Qt.MouseButton.LeftButton)

    qtbot.keyClick(newest, Qt.Key.Key_Up)
    qtbot.keyClick(newest, Qt.Key.Key_Return)

    assert asked == ["img1"]


def test_the_preview_carries_the_shown_generations_corner_controls(saved_panel):
    tab, db = saved_panel
    image = _image_row(db, "img1", filename="sdxl_img1.png")

    tab.show_saved_generation(image, [image])

    assert tab._viewport._actions_id == "img1"


def test_a_preview_corner_relays_the_act_with_the_id_it_is_about(saved_panel):
    tab, _db = saved_panel
    got = []
    tab.item_action_requested.connect(lambda pid, action: got.append((pid, action)))

    tab._viewport.action_triggered.emit("img1", corner_buttons.STAR)

    assert got == [("img1", corner_buttons.STAR)]


def test_a_favorite_preview_stays_favorite_through_an_enhance_setting_change(saved_panel):
    tab, db = saved_panel
    image = _image_row(db, "img1")
    tab.show_saved_generation(image, [image])
    db.set_generation_favorite("img1", True)

    tab.set_enhance_settings(gallery.EnhanceSettings(auto=True))

    assert tab._viewport._controls.buttons()[0].toolTip() == "Unfavorite this item"


def test_right_clicking_the_preview_asks_for_the_generations_menu(saved_panel):
    tab, _db = saved_panel
    got = []
    tab.context_menu_requested.connect(lambda pid, pos: got.append(pid))

    tab._viewport.context_requested.emit("img1", QPoint(4, 4))

    assert got == ["img1"]


def test_a_deleted_images_version_says_how_long_it_has_been_in_the_trash(saved_panel):
    tab, db = saved_panel
    image = dict(_image_row(db, "img1"), days_in_trash=2)

    tab.show_saved_generation(image, [image])

    files = [text for text in _version_texts(tab) if "sdxl_img1.png" in text]
    assert files
    assert all(text.startswith("(2 days in trash)") for text in files)


def _version_texts(tab):
    return [lbl.text().replace("\u200b", "")
            for lbl in tab._versions.findChildren(QLabel)]


def test_showing_a_saved_generation_arms_the_preview_drag(saved_panel, monkeypatch):
    tab, db = saved_panel
    monkeypatch.setattr(generate_tab_module, "resolve_preview", lambda row, out: ("img1.png", "image"))
    image = _image_row(db, "img1")

    tab.show_saved_generation(image, [image])

    assert tab._viewport.show_media.call_args.args == ("img1.png", "image", "img1")


def test_a_generation_with_no_file_leaves_the_preview_undraggable(saved_panel, monkeypatch):
    tab, db = saved_panel
    monkeypatch.setattr(generate_tab_module, "resolve_preview", lambda row, out: None)
    image = _image_row(db, "img1")

    tab.show_saved_generation(image, [image])

    assert tab._viewport._generation is None


def test_the_tab_watches_no_run_of_its_own(tab):
    tab.set_generating(True)
    assert tab._generate_btn.text() == "Generate"
    assert not hasattr(tab, "_on_progress"), (
        "filled with its run's steps, the button was a third, differently worded telling of one run, "
        "and tied the control that starts work to the state of work already going")
    assert not hasattr(tab, "_generating_prompt_id")


def test_a_tab_with_nothing_to_autoshow_clears_the_last_selections_footer(
        saved_panel, monkeypatch):
    tab, db = saved_panel
    image = _image_row(db, "img1", filename="sdxl_img1.png")
    tab.show_saved_generation(image, [image])
    assert not tab._versions.isHidden()

    monkeypatch.setattr(tab, "_recent_matching_row", lambda: None)
    tab.show_recent_preview()

    assert _shown_metadata(tab) == [TYPICAL_TIME]
    assert tab._versions.isHidden()
    assert source_tile(tab._related).isHidden()
    assert tab._lane_button.isHidden()


def _wizard_panel(qtbot, tmp_path, monkeypatch):
    output = tmp_path / "out"
    (output / "image").mkdir(parents=True)
    (output / "image" / "sdxl_g1.png").write_bytes(b"png")
    monkeypatch.setattr(generate_tab_module, "OUTPUT_PLACES", OutputPlaces.in_one_folder(output))
    db = Database(tmp_path / "t.db")
    db.insert_generation(NewGeneration(prompt_id="g1", workflow_name="sdxl_t2i",
                         workflow_version=_SDXL_VERSION, positive_prompt="a wizard",
                         params_json=json.dumps(_wiz_params()), workflow_json="{}"))
    db.update_generation("g1", status="completed", output_files=json.dumps(
        [{"filename": "sdxl_g1.png", "subfolder": "image"}]))
    tab = GenerateTab(ComfyUIClient(folders=SUITE_FOLDERS), db)
    qtbot.addWidget(tab)
    tab._viewport.show_media = MagicMock()
    return tab, db


def test_an_image_the_tab_puts_up_itself_carries_its_own_file_row(
        qtbot, tmp_path, monkeypatch):
    tab, _db = _wizard_panel(qtbot, tmp_path, monkeypatch)

    tab.prefill("sdxl_t2i", _wiz_params())

    assert tab.displayed_row()["prompt_id"] == "g1", (
        "the newest result of these settings is a real generation, not a peek: its file is reached "
        "from it exactly as from one that was clicked")
    (row,) = _version_rows(tab)
    assert "image/sdxl_g1.png" in _row_texts(row)
    names = [b.objectName() for b in row.findChildren(QPushButton)]
    assert names == ["copyButton", "revealButton"]


def test_a_video_whose_start_image_is_in_the_trash_still_shows_its_source(saved_panel):
    tab, db = saved_panel
    image = _image_row(db, "img1", filename="sdxl_img1.png")
    video = _video_row(db, "vid1", input_image="sdxl_img1.png")
    db.record_trashed("img1", image, {"moves": [], "subdir": None})
    db.delete_generation("img1")

    tab.show_saved_generation(video, [])

    assert not source_tile(tab._related).isHidden()
    assert source_tile(tab._related)._prompt_id == "img1"


def test_showing_an_image_lists_the_videos_it_was_animated_into(saved_panel, monkeypatch):
    tab, db = saved_panel
    image = _image_row(db, "img1", filename="sdxl_img1.png")
    _video_row(db, "vid1", input_image="sdxl_img1.png")
    image_rows = [image]

    tab.show_saved_generation(image, image_rows)

    assert not tab._related._animations.isHidden()
    assert len(tab._related._animations.findChildren(SourceTile)) == 1
    assert source_tile(tab._related).isHidden()
    assert tab._lane_button.isHidden()
    assert tab._displayed_row is image


def test_a_click_on_an_image_s_animation_is_a_link_clicked(saved_panel, monkeypatch):
    tab, db = saved_panel
    image = _image_row(db, "img1", filename="sdxl_img1.png")
    _video_row(db, "vid1", input_image="sdxl_img1.png")
    tab.show_saved_generation(image, [image])
    got = []
    tab.link_clicked.connect(got.append)

    tab._related._animations.activated.emit("vid1")

    assert got == ["vid1"]


def test_showing_a_video_reveals_evolver_and_source_tile(saved_panel, monkeypatch):
    tab, db = saved_panel
    image = _image_row(db, "img1", filename="sdxl_img1.png")
    video = _video_row(db, "vid1", input_image="sdxl_img1.png")
    name = _named(tab, image)
    monkeypatch.setattr(generate_tab_module, "resolve_preview",
                        lambda row, out: (Path("C:/out/vid1.mp4"), "video"))

    tab.show_saved_generation(video, [image])

    assert not tab._lane_button.isHidden()
    assert not source_tile(tab._related).isHidden()
    assert source_tile(tab._related)._prompt_id == "img1"
    assert source_tile(tab._related)._name.text() == name
    assert [tile.heading for tile in tab._related._animations.findChildren(SourceTile)
            if not tile.isHidden()] == ["Animated from"]


def test_a_video_from_another_source_is_never_offered_to_evolver(saved_panel, monkeypatch,
                                                                    tmp_path):
    tab, db = saved_panel
    file = tmp_path / "outbox" / "portrait" / "a-site" / "c1_topaz.mp4"
    file.parent.mkdir(parents=True)
    file.write_bytes(b"not really a video")
    db.insert_rows(rows_bringing_in(
        OutsideVideo(file, "a-site"), Record(), FrameFolders(tmp_path / "frames", tmp_path / "thumbs"),
        grab=lambda _path: Image.new("RGB", (64, 96))))
    [video] = [row for row in db.list_generations()
               if gallery_media_type(row) == MediaType.VIDEO]
    monkeypatch.setattr(generate_tab_module, "resolve_preview", lambda row, out: (file, "video"))

    tab.show_saved_generation(video, [])

    assert tab._lane_button.isHidden(), (
        "Evolver already holds every other source's videos")
    assert tab._sent_row.isHidden()


def test_a_click_on_a_video_s_start_frame_is_a_link_clicked(saved_panel, monkeypatch):
    tab, db = saved_panel
    image = _image_row(db, "img1", filename="sdxl_img1.png")
    video = _video_row(db, "vid1", input_image="sdxl_img1.png")
    monkeypatch.setattr(generate_tab_module, "resolve_preview",
                        lambda row, out: (Path("C:/out/vid1.mp4"), "video"))
    tab.show_saved_generation(video, [image])
    got = []
    tab.link_clicked.connect(got.append)

    source_tile(tab._related).activated.emit("img1")

    assert got == ["img1"]


def test_video_without_a_known_source_hides_the_link(saved_panel, monkeypatch):
    tab, db = saved_panel
    video = _video_row(db, "vid1", input_image="hand_placed.png")
    monkeypatch.setattr(generate_tab_module, "resolve_preview",
                        lambda row, out: (Path("C:/out/vid1.mp4"), "video"))

    tab.show_saved_generation(video, [])

    assert source_tile(tab._related).isHidden()
    assert not tab._lane_button.isHidden()


def _script_for(video_path, output_dir=None):
    actions = synthesize_actions(2.0, hz=1.0)
    dest = (video_path.with_suffix(".funscript") if output_dir is None
            else funscript_path_for(video_path, places=OutputPlaces.in_one_folder(output_dir)))
    write_funscript(dest, actions)
    return actions


def test_osr2_drive_target_gives_path_player_and_actions_for_a_scripted_video(
    saved_panel, monkeypatch, tmp_path
):
    tab, db = saved_panel
    video = _video_row(db, "vid1", input_image="hand.png")
    vpath = tmp_path / "vid1.mp4"
    vpath.write_bytes(b"v")
    actions = _script_for(vpath)
    monkeypatch.setattr(generate_tab_module, "resolve_preview", lambda row, out: (vpath, "video"))
    tab.show_saved_generation(video, [])

    assert tab.osr2_drive_target() == (vpath, tab._viewport.player(), actions)


def test_osr2_drive_target_reads_the_scripts_folder(saved_panel, monkeypatch, tmp_path):
    tab, db = saved_panel
    video = _video_row(db, "vid1", input_image="hand.png")
    vpath = tmp_path / "video" / "vid1.mp4"
    vpath.parent.mkdir()
    vpath.write_bytes(b"v")
    monkeypatch.setattr(osr2_driver, "OUTPUT_PLACES", OutputPlaces.in_one_folder(tmp_path))
    actions = _script_for(vpath, output_dir=tmp_path)
    monkeypatch.setattr(generate_tab_module, "resolve_preview", lambda row, out: (vpath, "video"))
    tab.show_saved_generation(video, [])

    assert tab.osr2_drive_target() == (vpath, tab._viewport.player(), actions)


def test_osr2_drive_target_is_none_for_a_video_without_a_funscript(saved_panel, monkeypatch, tmp_path):
    tab, db = saved_panel
    video = _video_row(db, "vid1", input_image="hand.png")
    vpath = tmp_path / "vid1.mp4"
    vpath.write_bytes(b"v")
    monkeypatch.setattr(generate_tab_module, "resolve_preview", lambda row, out: (vpath, "video"))
    tab.show_saved_generation(video, [])

    assert tab.osr2_drive_target() is None


def test_osr2_drive_target_is_none_for_an_image(saved_panel, monkeypatch):
    tab, db = saved_panel
    image = _image_row(db, "img1", filename="i.png")
    monkeypatch.setattr(generate_tab_module, "resolve_preview", lambda row, out: (Path("C:/i.png"), "image"))
    tab.show_saved_generation(image, [image])

    assert tab.osr2_drive_target() is None


def test_osr2_drive_target_follows_an_idle_autoshow_not_just_a_selection(
    saved_panel, monkeypatch, tmp_path
):
    tab, _db = saved_panel
    vpath = tmp_path / "auto.mp4"
    vpath.write_bytes(b"v")
    actions = _script_for(vpath)
    monkeypatch.setattr(tab, "_recent_matching_row",
                        lambda: {"prompt_id": "v", "workflow_name": "wan22_i2v"})
    monkeypatch.setattr(generate_tab_module, "resolve_preview", lambda row, out: (vpath, "video"))

    tab.show_recent_preview()

    assert tab.osr2_drive_target() == (vpath, tab._viewport.player(), actions)


def test_showing_a_generation_emits_displayed_changed(saved_panel, monkeypatch, tmp_path):
    tab, db = saved_panel
    video = _video_row(db, "vid1", input_image="hand.png")
    vpath = tmp_path / "vid1.mp4"
    vpath.write_bytes(b"v")
    _script_for(vpath)
    monkeypatch.setattr(generate_tab_module, "resolve_preview", lambda row, out: (vpath, "video"))
    fired = []
    tab.displayed_changed.connect(lambda: fired.append(True))

    tab.show_saved_generation(video, [])
    assert fired == [True]


def test_showing_a_video_seeds_the_form_with_its_params(saved_panel, monkeypatch):
    tab, db = saved_panel
    video = _video_row(db, "vid1", input_image="sdxl_img1.png")
    monkeypatch.setattr(generate_tab_module, "resolve_preview",
                        lambda row, out: (Path("C:/out/vid1.mp4"), "video"))

    tab.show_saved_generation(video, [])

    assert tab._workflow_dropdown.currentData() == "wan22_i2v"
    assert tab._param_form.get_values()["positive_prompt"] == "dance"


def test_completed_result_shows_output_and_footer_and_keeps_the_edit_in_flight(saved_panel):
    tab, db = saved_panel
    image = _image_row(db, "img1", prompt="a cat", filename="sdxl_img1.png")
    tab._param_form.set_values({"positive_prompt": "a wizard mid-edit"})

    tab.show_completed_result(image, [image])

    assert tab._param_form.get_values()["positive_prompt"] == "a wizard mid-edit"
    assert tab._displayed_row is image
    assert not tab._versions.isHidden()


def test_a_seed_pinned_while_the_run_was_in_flight_stays_pinned_when_it_lands(saved_panel):
    tab, db = saved_panel
    image = _image_row(db, "img1", prompt="a cat", filename="sdxl_img1.png")
    tab._param_form._widgets["seed"].setEditText("99")
    tab._param_form.set_seed_random(False)

    tab.show_completed_result(image, [image])

    assert tab._param_form.get_values()["seed"] == 99


def test_showing_an_unregistered_generation_still_shows_preview_and_footer(saved_panel, monkeypatch):
    tab, db = saved_panel
    db.insert_generation(NewGeneration(
        prompt_id="u1", workflow_name="unknown", workflow_version="imported",
        params_json=json.dumps({"steps": 20}), workflow_json="{}",
    ))
    db.update_generation("u1", status="completed",
                         output_files=json.dumps([{"filename": "u1.mp4", "subfolder": "video"}]))
    row = db.get_generation("u1")
    monkeypatch.setattr(generate_tab_module, "resolve_preview",
                        lambda r, out: (Path("C:/out/u1.mp4"), "video"))

    tab.show_saved_generation(row, [])

    assert not tab._lane_button.isHidden()
    assert tab._displayed_row is row


def test_showing_a_saved_generation_shows_its_preview_over_the_autoshow(saved_panel, monkeypatch):
    tab, db = saved_panel
    video = _video_row(db, "vid1")
    monkeypatch.setattr(generate_tab_module, "resolve_preview",
                        lambda row, out: (Path("C:/out/vid1.mp4"), "video"))

    tab.show_saved_generation(video, [])

    assert tab._viewport.show_media.call_args.args == (Path("C:/out/vid1.mp4"), "video",
                                                         "vid1")


def test_a_click_puts_up_only_the_image_it_was_on(qtbot, tmp_path, monkeypatch):
    tab, db = _wizard_panel(qtbot, tmp_path, monkeypatch)
    row = db.get_generation("g1")

    tab.show_saved_generation(row, [row])

    assert tab._viewport.show_media.call_count == 1


def _gaps_between_sections(tab, scroll) -> dict[str, int]:
    body = scroll.widget()
    tab.layout().activate()

    def top(widget):
        return widget.mapTo(body, QPoint(0, 0)).y()

    shown = sorted((section for section in body.findChildren(CollapsibleSection)
                    if section.isVisibleTo(body)), key=top)
    return {lower.title(): top(lower) - (top(upper) + upper.height())
            for upper, lower in pairwise(shown)}


def test_each_area_keeps_one_gap_between_its_sections(saved_panel):
    tab, db = saved_panel
    image = _enhanced_image_row(db)
    tab.show_saved_generation(image, [image])
    tab.resize(480, 1400)
    tab.show()

    gaps = {**_gaps_between_sections(tab, tab._item_scroll),
            **_gaps_between_sections(tab, tab._settings_scroll)}

    assert {"Enhancements", "Request"} <= set(gaps)
    assert gaps == dict.fromkeys(gaps, GAP_MEDIUM)


def test_the_items_name_heads_the_column_in_line_with_the_sections_under_it(saved_panel):
    tab, db = saved_panel
    image = _image_row(db)
    tab.show_saved_generation(_video_row(db, input_image="sdxl_img1.png"), [image])
    tab.resize(480, 1600)
    tab.show()
    tab.layout().activate()
    body = tab._item_scroll.widget()

    def corner(widget):
        return widget.mapTo(body, QPoint(0, 0))

    def span(widget):
        return corner(widget).x(), corner(widget).x() + widget.width()

    name = tab._metadata_section.findChild(CollapsibleSection)
    spans = {section.title(): span(section) for section in body.findChildren(CollapsibleSection)
             if section.isVisibleTo(body)}

    assert spans == dict.fromkeys(spans, span(name))
    assert corner(name).y() == body.layout().contentsMargins().top()
    actions = tab._action.form().parentWidget().findChild(
        QWidget, action_pills(MediaType.IMAGE)).parentWidget()
    assert name.content().isAncestorOf(actions)


def _message(tab):
    return "" if tab._viewport._message.isHidden() else tab._viewport._message.text()


def _set_prompt(tab, text):
    _positive_field(tab).setPlainText(text)


def test_a_browsed_generation_arrives_unmarked(saved_panel):
    tab, db = saved_panel
    image = _image_row(db, "img1", prompt="a cat")
    tab.show_saved_generation(image, [image])
    assert _message(tab) == ""


def test_editing_a_setting_marks_the_image_as_not_generated_yet(saved_panel):
    tab, db = saved_panel
    image = _image_row(db, "img1", prompt="a cat")
    tab.show_saved_generation(image, [image])

    _set_prompt(tab, "a dog")

    assert _message(tab) == "(not yet generated with modifications)"


def test_putting_the_setting_back_clears_the_mark(saved_panel):
    tab, db = saved_panel
    image = _image_row(db, "img1", prompt="a cat")
    tab.show_saved_generation(image, [image])
    _set_prompt(tab, "a dog")

    _set_prompt(tab, "a cat")

    assert _message(tab) == ""


def _video_of_a_workflow_the_app_lacks(db, workflow_name, prompt_id="old1"):
    db.insert_generation(NewGeneration(
        prompt_id=prompt_id, workflow_name=workflow_name, workflow_version="v001",
        positive_prompt="scene one", seed=5,
        params_json=json.dumps({"positive_prompt": "scene one", "seed": 5}), workflow_json="{}",
    ))
    db.update_generation(prompt_id, status="completed",
                         output_files=json.dumps([{"filename": f"{prompt_id}.mp4", "subfolder": "video"}]))
    return db.get_generation(prompt_id)


def _note(tab):
    note = tab._cannot_remake_note
    if note.isHidden():
        return ""
    words = QTextDocumentFragment.fromHtml(note.text()).toPlainText()
    return words.replace("\u200b", "").lstrip("\ufffc\xa0 ")


_RETIRED_NOTE = ("This was made with WAN 2.1 I2V (Motion-Tracked), which has been "
                 "retired, so no new ones can be made. Select a workflow above to make something new.")


def test_a_video_from_a_retired_workflow_says_so_under_the_workflow_dropdown(saved_panel):
    tab, db = saved_panel
    video = _video_of_a_workflow_the_app_lacks(db, "wan21_ati_i2v")

    tab.show_saved_generation(video, [])

    assert _note(tab) == _RETIRED_NOTE
    assert _message(tab) == ""


def test_the_note_under_the_workflow_dropdown_leads_with_the_familys_warning(saved_panel):
    tab, db = saved_panel
    video = _video_of_a_workflow_the_app_lacks(db, "wan21_ati_i2v")

    tab.show_saved_generation(video, [])

    note = tab._cannot_remake_note
    assert note.text().startswith(inline_icon("warning", color=YELLOW, size=note.fontMetrics().height()))


def test_a_retired_workflows_video_leaves_no_settings_from_before(saved_panel):
    tab, db = saved_panel
    image = _image_row(db, "img1", prompt="a cat")
    tab.show_saved_generation(image, [image])
    video = _video_of_a_workflow_the_app_lacks(db, "wan21_ati_i2v")

    tab.show_saved_generation(video, [image])

    assert tab._workflow_dropdown.currentIndex() == -1
    assert tab._param_form is None


def test_a_retired_workflows_video_lists_the_video_workflows_to_make_another_with(saved_panel):
    tab, db = saved_panel
    image = _image_row(db, "img1", prompt="a cat")
    tab.show_saved_generation(image, [image])
    video = _video_of_a_workflow_the_app_lacks(db, "wan21_ati_i2v")

    tab.show_saved_generation(video, [image])

    assert _listed_workflows(tab) == _offered(MediaType.VIDEO)


def test_an_import_from_a_workflow_the_app_never_had_says_so(saved_panel):
    tab, db = saved_panel
    video = _video_of_a_workflow_the_app_lacks(db, "unknown")

    tab.show_saved_generation(video, [])

    assert _note(tab) == ("This was made with a workflow Origenerator doesn't have, so no new "
                            "ones can be made. Select a workflow above to make something new.")


def test_generate_says_why_it_is_grayed_out_beside_such_a_video(saved_panel):
    tab, db = saved_panel
    video = _video_of_a_workflow_the_app_lacks(db, "wan21_ati_i2v")
    tab.show_saved_generation(video, [])

    tab._apply_generate_caption()

    assert not tab._generate_pair.isEnabled()
    assert tab._generate_btn.toolTip() == ("WAN 2.1 I2V (Motion-Tracked) has been "
                                             "retired — select a workflow first")


def test_generate_says_why_it_is_grayed_out_beside_an_import_from_a_workflow_the_app_never_had(
        saved_panel):
    tab, db = saved_panel
    video = _video_of_a_workflow_the_app_lacks(db, "unknown")
    tab.show_saved_generation(video, [])

    tab._apply_generate_caption()

    assert tab._generate_btn.toolTip() == ("Origenerator doesn't have the workflow this was "
                                             "made with — select a workflow first")


def test_selecting_a_workflow_after_such_a_video_clears_the_note_and_brings_generate_back(
        saved_panel):
    tab, db = saved_panel
    video = _video_of_a_workflow_the_app_lacks(db, "wan21_ati_i2v")
    tab.show_saved_generation(video, [])

    tab._workflow_dropdown.setCurrentIndex(_dropdown_index(tab, "wan22_i2v"))
    tab._param_form.set_values({"input_image": "frame.png [output]"})

    assert _note(tab) == ""
    assert tab._generate_pair.isEnabled()


def _image_made_with(db, checkpoint, prompt_id="img9"):
    params = dict(WORKFLOW_REGISTRY["sdxl_t2i"].default_params(),
                  positive_prompt="scene one", seed=1, checkpoint=checkpoint)
    db.insert_generation(NewGeneration(
        prompt_id=prompt_id, workflow_name="sdxl_t2i", workflow_version="v002",
        positive_prompt="scene one", seed=1, params_json=json.dumps(params), workflow_json="{}",
    ))
    db.update_generation(prompt_id, status="completed",
                         output_files=json.dumps([{"filename": f"{prompt_id}.png", "subfolder": "image"}]))
    return db.get_generation(prompt_id)


def test_an_image_made_with_a_model_that_is_not_installed_says_so_under_the_workflow_dropdown(
        installed_models, saved_panel):
    tab, db = saved_panel
    image = _image_made_with(db, "retired_checkpoint.safetensors")

    tab.show_saved_generation(image, [image])

    assert _note(tab) == ("This was made with retired_checkpoint, which isn't installed "
                            "anymore, so no new ones can be made with it until an installed one "
                            "is picked in its place.")
    assert _message(tab) == ""


def test_the_note_and_the_typical_time_are_metadata(installed_models, saved_panel):
    tab, db = saved_panel
    image = _image_made_with(db, "retired_checkpoint.safetensors")
    tab.show_saved_generation(image, [image])
    metadata = tab._metadata_section.findChild(CollapsibleSection).content()

    assert (metadata.isAncestorOf(tab._cannot_remake_note),
            metadata.isAncestorOf(tab._estimate_label)) == (True, True)
    assert "Typical time" in [label.text() for label in metadata.findChildren(ElidingLabel)]


def test_the_note_wears_the_yellow_of_a_warning(app_chrome, installed_models, saved_panel):
    tab, db = saved_panel
    image = _image_made_with(db, "retired_checkpoint.safetensors")
    tab.show_saved_generation(image, [image])
    note = tab._cannot_remake_note

    note.ensurePolished()

    assert note.palette().color(note.foregroundRole()).name() == YELLOW.name()


def test_a_long_model_name_in_the_note_wraps_rather_than_scrolling_sideways(
        installed_models, saved_panel):
    tab, db = saved_panel
    image = _image_made_with(
        db, "an_invented_checkpoint_whose_name_runs_on_and_on_and_on_v1.safetensors")
    tab.show_saved_generation(image, [image])
    tab.show()

    tab.resize(300, 800)
    QApplication.processEvents()

    assert not tab._cannot_remake_note.isHidden()
    assert not tab._settings_scroll.horizontalScrollBar().isVisible()


def test_the_missing_models_field_wears_a_warning_that_puts_an_installed_one_in_its_place(
        installed_models, saved_panel):
    tab, db = saved_panel
    image = _image_made_with(db, "retired_checkpoint.safetensors")
    tab.show_saved_generation(image, [image])
    mark = tab._param_form._warning_marks["checkpoint"]
    assert not mark.isHidden()
    assert mark.toolTip() == ("Not installed anymore, so nothing can be made with it. "
                              "Click to use reapony_v80.")

    mark.pressed.emit()

    assert tab._param_form.get_values()["checkpoint"] == "reapony_v80.safetensors"
    assert _note(tab) == ""
    assert tab._generate_pair.isEnabled()


def test_a_model_installed_but_not_made_for_the_workflow_says_so_rather_than_not_installed(
        installed_models, saved_panel):
    installed_models.add("checkpoints", "an_old_look.safetensors", arch="sd15")
    tab, db = saved_panel
    image = _image_made_with(db, "an_old_look.safetensors")

    tab.show_saved_generation(image, [image])

    mark = tab._param_form._warning_marks["checkpoint"]
    assert (mark.isHidden(), mark.toolTip()) == (
        False, ("an_old_look isn't made for SDXL T2I, so it isn't offered here. "
                "Click to use reapony_v80."))
    assert _note(tab) == ""
    assert tab._generate_pair.isEnabled()


def test_a_lora_not_made_for_the_model_beside_it_says_so_on_its_row(
        installed_models, recorded_base_models, saved_panel):
    for model in ("raw_model", "turbo_model"):
        installed_models.add("diffusion_models", f"{model}.safetensors", arch="krea2")
    installed_models.add("loras", "speed_up.safetensors", arch="krea2", lora=True)
    recorded_base_models({"raw_model": "Krea 2", "turbo_model": "Krea 2 Turbo",
                          "speed_up": "Krea 2 Raw"})
    tab, _db = saved_panel
    tab._workflow_dropdown.setCurrentIndex(_dropdown_index(tab, "krea2_t2i"))

    tab._param_form.set_values({"unet": "turbo_model.safetensors",
                                  "lora": "speed_up.safetensors"})

    mark = tab._param_form._warning_marks["lora"]
    assert (mark.isHidden(), mark.toolTip()) == (
        False, ("speed_up isn't made for turbo_model, so it isn't offered here. "
                "Click to use None."))


def test_generate_is_grayed_out_while_the_form_names_a_model_that_is_not_installed(
        installed_models, saved_panel):
    tab, db = saved_panel
    image = _image_made_with(db, "retired_checkpoint.safetensors")
    tab.show_saved_generation(image, [image])

    _set_prompt(tab, "scene two")

    assert not tab._generate_pair.isEnabled()
    assert tab._generate_btn.toolTip() == ("retired_checkpoint isn't installed anymore — pick an "
                                             "installed one first")


def test_picking_an_installed_model_brings_generate_back(installed_models, saved_panel):
    tab, db = saved_panel
    image = _image_made_with(db, "retired_checkpoint.safetensors")
    tab.show_saved_generation(image, [image])
    checkpoint = tab._param_form._widgets["checkpoint"]

    checkpoint.setCurrentIndex(
        checkpoint.findData(WORKFLOW_REGISTRY["sdxl_t2i"].default_params()["checkpoint"]))

    assert tab._generate_pair.isEnabled()
    assert _note(tab) == ""
    assert _message(tab) == "(not yet generated with modifications)"


def test_a_video_made_with_two_models_that_are_not_installed_names_both(installed_models, saved_panel):
    tab, db = saved_panel
    params = dict(WORKFLOW_REGISTRY["wan22_i2v"].default_params(), positive_prompt="scene one",
                  unet_high="retired_high.safetensors", unet_low="retired_low.safetensors")
    db.insert_generation(NewGeneration(
        prompt_id="vid9", workflow_name="wan22_i2v", workflow_version="v002",
        positive_prompt="scene one", seed=5, params_json=json.dumps(params), workflow_json="{}",
    ))
    db.update_generation("vid9", status="completed",
                         output_files=json.dumps([{"filename": "vid9.mp4", "subfolder": "video"}]))
    video = db.get_generation("vid9")

    tab.show_saved_generation(video, [])

    assert _note(tab) == ("This was made with retired_high and retired_low, which aren't "
                            "installed anymore, so no new ones can be made with them until "
                            "installed ones are picked in their place.")


def test_editing_a_shown_image_s_prompt_marks_how_it_now_differs(saved_panel, qtbot):
    tab, db = saved_panel
    image = _image_row(db, "img1", prompt="a cat on a couch")
    tab.show_saved_generation(image, [image])
    field = _positive_field(tab)

    field.setPlainText("a dog on a couch")

    qtbot.waitUntil(lambda: _struck_and_lit(field) == ("cat", "dog"), timeout=5000)
    assert _message(tab) == "(not yet generated with modifications)"


def test_undoing_a_prompt_edit_takes_the_message_back_down(saved_panel, qtbot):
    tab, db = saved_panel
    image = _image_row(db, "img1", prompt="a cat on a couch")
    tab.show_saved_generation(image, [image])
    field = _positive_field(tab)
    field.moveCursor(QTextCursor.MoveOperation.End)
    qtbot.keyClicks(field, "s")
    qtbot.waitUntil(lambda: _struck_and_lit(field) == ("couch", "couchs"), timeout=5000)

    qtbot.keyClick(field, Qt.Key.Key_Z, Qt.KeyboardModifier.ControlModifier)

    qtbot.waitUntil(lambda: diff_text.live_text(field) == "a cat on a couch", timeout=5000)
    assert _message(tab) == ""


def test_showing_the_image_a_tab_already_shows_still_marks_what_is_typed(saved_panel, qtbot):
    tab, db = saved_panel
    image = _image_row(db, "img1", prompt="a cat on a couch")
    tab.show_saved_generation(image, [image])

    tab.show_saved_generation(image, [image])

    field = _positive_field(tab)
    field.setPlainText("a dog on a couch")
    qtbot.waitUntil(lambda: _struck_and_lit(field) == ("cat", "dog"), timeout=5000)


def _each_press_launches_a_run(tab):
    def launch(*_press):
        tab.note_launched(f"run {len(tab.launched_runs())}",
                          made_of=tab._param_form.get_values())
    tab.generate_requested.connect(launch)
    tab.modify_batch_requested.connect(launch)


def test_generate_takes_the_red_and_green_off_its_prompts(saved_panel, qtbot):
    tab, db = saved_panel
    _each_press_launches_a_run(tab)
    image = _image_row(db, "img1", prompt="a cat on a couch")
    tab.show_saved_generation(image, [image])
    field = _positive_field(tab)
    field.setPlainText("a dog on a couch")
    qtbot.waitUntil(lambda: _struck_and_lit(field) == ("cat", "dog"), timeout=5000)

    tab._on_generate()

    assert _struck_and_lit(field) == ("", "")
    assert field.toPlainText() == "a dog on a couch"


def test_a_press_that_starts_no_run_leaves_the_red_and_green(saved_panel, qtbot):
    tab, db = saved_panel
    image = _image_row(db, "img1", prompt="a cat on a couch")
    tab.show_saved_generation(image, [image])
    field = _positive_field(tab)
    field.setPlainText("a dog on a couch")
    qtbot.waitUntil(lambda: _struck_and_lit(field) == ("cat", "dog"), timeout=5000)

    tab._on_generate()

    assert _struck_and_lit(field) == ("cat", "dog")


def test_the_red_and_green_come_back_only_when_the_last_press_has_ended(saved_panel, qtbot):
    tab, db = saved_panel
    _each_press_launches_a_run(tab)
    image = _image_row(db, "img1", prompt="a cat on a couch")
    tab.show_saved_generation(image, [image])
    field = _positive_field(tab)
    field.setPlainText("a dog on a couch")
    tab._on_generate()
    field.setPlainText("a dog on a rug")
    tab._on_generate()

    tab.forget_launched({"run 1"})
    assert _struck_and_lit(field) == ("couch", "rug")

    tab.forget_launched({"run 0"})
    assert "cat" in _struck_and_lit(field)[0]


def test_a_run_the_tab_only_took_up_leaves_the_red_and_green(saved_panel, qtbot):
    tab, db = saved_panel
    image = _image_row(db, "img1", prompt="a cat on a couch")
    tab.show_saved_generation(image, [image])
    field = _positive_field(tab)
    field.setPlainText("a dog on a couch")
    qtbot.waitUntil(lambda: _struck_and_lit(field) == ("cat", "dog"), timeout=5000)

    tab.note_launched("a run of Populate")

    assert _struck_and_lit(field) == ("cat", "dog")


def test_what_is_typed_after_generate_is_marked_against_what_it_made(saved_panel, qtbot):
    tab, db = saved_panel
    _each_press_launches_a_run(tab)
    image = _image_row(db, "img1", prompt="a cat on a couch")
    tab.show_saved_generation(image, [image])
    field = _positive_field(tab)
    field.setPlainText("a dog on a couch")
    tab._on_generate()

    field.setPlainText("a dog on a rug")

    qtbot.waitUntil(lambda: _struck_and_lit(field) == ("couch", "rug"), timeout=5000)


def test_undo_after_generate_takes_back_what_was_typed_before_it(saved_panel, qtbot):
    tab, db = saved_panel
    _each_press_launches_a_run(tab)
    image = _image_row(db, "img1", prompt="a cat on a couch")
    tab.show_saved_generation(image, [image])
    field = _positive_field(tab)
    field.moveCursor(QTextCursor.MoveOperation.End)
    qtbot.keyClicks(field, "s")
    tab._on_generate()

    qtbot.keyClick(field, Qt.Key.Key_Z, Qt.KeyboardModifier.ControlModifier)

    assert diff_text.live_text(field) == "a cat on a couch"
    assert _struck_and_lit(field) == ("couchs", "couch")


def test_showing_the_next_image_never_reaches_the_marks_as_typing(saved_panel, monkeypatch):
    tab, db = saved_panel
    first = _image_row(db, "img1", prompt="a cat on a couch")
    second = _image_row(db, "img2", prompt="a dog in a park", filename="sdxl_img2.png")
    typed = []
    follow = _Tracker._on_contents_change

    def following(tracker, *change):
        if not tracker._writing:
            typed.append(change)
        follow(tracker, *change)

    monkeypatch.setattr(_Tracker, "_on_contents_change", following)
    tab.show_saved_generation(first, [first])

    tab.show_saved_generation(second, [second])

    assert typed == []


def test_a_finished_run_arrives_marked_while_random_is_ticked(saved_panel):
    tab, db = saved_panel
    image = _image_row(db, "img1", prompt="a cat")

    tab.show_completed_result(image, [image])

    assert tab._param_form.seed_is_random() is True
    assert tab._param_form.get_values()["seed"] != image["seed"]
    assert _message(tab) == "(not yet generated with modifications)"


def test_re_rolling_the_seed_marks_it_too(saved_panel):
    tab, db = saved_panel
    image = _image_row(db, "img1")
    tab.show_saved_generation(image, [image])

    tab._param_form.set_seed_random(True)

    assert _message(tab) == "(not yet generated with modifications)"


def test_a_tab_with_nothing_on_display_is_never_marked(tab):
    _set_prompt(tab, "a dog")
    assert tab._displayed_row is None
    assert _message(tab) == ""


def _resting_on(tab, image, monkeypatch, tmp_path):
    ipath = tmp_path / "sdxl_img1.png"
    ipath.write_bytes(b"p")
    monkeypatch.setattr(tab, "_recent_matching_row", lambda: image)
    monkeypatch.setattr(generate_tab_module, "resolve_preview", lambda row, out: (ipath, "image"))
    tab.show_recent_preview()


def test_the_idle_autoshow_is_marked_once_the_form_moves_off_it(
    saved_panel, monkeypatch, tmp_path
):
    tab, db = saved_panel
    image = _image_row(db, "img1", prompt="a cat")
    tab._param_form.set_values({"seed": image["seed"]})

    _resting_on(tab, image, monkeypatch, tmp_path)
    assert tab._displayed_row is not None
    assert _message(tab) == ""

    _set_prompt(tab, "a dog")

    assert _message(tab) == "(not yet generated with modifications)"


def test_the_idle_autoshow_is_marked_while_random_is_ticked(saved_panel, monkeypatch, tmp_path):
    tab, db = saved_panel
    image = _image_row(db, "img1", prompt="a cat")

    _resting_on(tab, image, monkeypatch, tmp_path)

    assert _message(tab) == "(not yet generated with modifications)"


def test_switching_workflow_leaves_no_stale_mark(saved_panel):
    tab, db = saved_panel
    image = _image_row(db, "img1", prompt="a cat")
    tab.show_saved_generation(image, [image])
    _set_prompt(tab, "a dog")
    assert _message(tab) != ""

    tab._workflow_dropdown.setCurrentIndex(_dropdown_index(tab, "flux_t2i_upscaled"))

    assert _message(tab) == ""


def _frame_bytes(tmp_path, size: int = 8) -> bytes:
    path = tmp_path / f"frame{size}.png"
    pixmap = QPixmap(size, 6)
    pixmap.fill()
    pixmap.save(str(path), "PNG")
    return path.read_bytes()


def test_an_enhancement_streaming_in_leaves_the_mark_standing(saved_panel, tmp_path):
    tab, db = saved_panel
    image = _image_row(db, "img1", prompt="a cat")
    tab.show_saved_generation(image, [image])
    _set_prompt(tab, "a dog")

    tab.set_pending_enhancement(RunningEnhancement("running", _frame_bytes(tmp_path), "2x"))

    assert _message(tab) == "(not yet generated with modifications)"

    tab.set_pending_enhancement(RunningEnhancement("running", _frame_bytes(tmp_path, 10), "2x"))

    assert _message(tab) == "(not yet generated with modifications)"


def test_the_enhancement_landing_leaves_the_mark_standing(saved_panel, tmp_path,
                                                          monkeypatch):
    tab, db = saved_panel
    output_dir = tmp_path / "out"
    (output_dir / "image").mkdir(parents=True)
    for name in ("sdxl_img1.png", "image_enhance_00001_.png"):
        (output_dir / "image" / name).write_bytes(b"x")
    monkeypatch.setattr(generate_tab_module, "OUTPUT_PLACES", OutputPlaces.in_one_folder(output_dir))

    image = _image_row(db, "img1", prompt="a cat")
    tab.show_saved_generation(image, [image])
    _set_prompt(tab, "a dog")
    tab.set_pending_enhancement(RunningEnhancement("running", _frame_bytes(tmp_path), "2x"))

    enhanced = _fold_enhancement(db, "img1")
    tab.refresh_displayed(enhanced, [enhanced])
    tab.set_pending_enhancement(None)

    assert _message(tab) == "(not yet generated with modifications)", (
        "nothing about the settings moved when the enhancement folded in; measured from there "
        "afresh, the user's edits would read as what was generated")


def test_a_live_frame_clears_the_mark_it_answers(saved_panel):
    tab, db = saved_panel
    image = _image_row(db, "img1", prompt="a cat")
    tab.show_saved_generation(image, [image])
    _set_prompt(tab, "a dog")

    tab._viewport.show_message("Waiting for preview…", live=True)

    assert _message(tab) == ""



def _request_made(db, prompt_id, source="src", asked="no hat", answered="Done."):
    db.record_request(NewRequest(prompt_id=prompt_id, source_prompt_id=source,
                      heard=f"Request, {asked}, over.", asked=asked,
                      old_positive="a cat, a hat", old_negative="blurry",
                      new_positive="a cat", new_negative="blurry, hat"))
    db.requests.record_turns(prompt_id, [Turn(asked, answered, "a cat, a hat", "blurry", "a cat",
                                     "blurry, hat")])


def _struck_and_lit_in(html: str) -> tuple[str, str]:
    document = QTextDocument()
    document.setHtml(html)
    cursor = QTextCursor(document)
    struck = lit = ""
    for position in range(len(document.toPlainText())):
        cursor.setPosition(position)
        cursor.setPosition(position + 1, QTextCursor.MoveMode.KeepAnchor)
        fmt = cursor.charFormat()
        if fmt.fontStrikeOut():
            struck += cursor.selectedText()
        elif fmt.background().style() != Qt.BrushStyle.NoBrush:
            lit += cursor.selectedText()
    return struck.strip(), lit.strip()


def _rewriting(monkeypatch, answer=("two women on a couch", "blurry"), changes=None):
    calls = []
    answers = list(answer) if isinstance(answer, list) else []

    def ask_the_model(positive, negative, words, known):
        calls.append((positive, negative, words))
        current = answers.pop(0) if answers else answer
        if isinstance(current, Exception):
            raise current
        return (*current, "Done.", changes)

    monkeypatch.setattr(prompt_edit, "ask_the_model", ask_the_model)
    return calls


def _ask(tab, qtbot, words):
    exchange = tab._param_form.request_exchange()
    qtbot.keyClicks(exchange._line, words)
    qtbot.keyClick(exchange._line, Qt.Key.Key_Return)
    return exchange


def _positive(tab):
    return tab._param_form._widgets["positive_prompt"].value()


def test_an_image_a_request_made_shows_the_exchange_in_the_request_section(saved_panel):
    tab, db = saved_panel
    image = _image_row(db, "img1", prompt="a cat")
    _request_made(db, "img1", answered="Took the hat off the cat.")

    tab.show_saved_generation(image, [image])

    exchange = tab._param_form.request_exchange()
    assert exchange.turns() == [("no hat", "Took the hat off the cat.")]
    assert exchange._line.isEnabled()


def test_the_exchange_runs_back_through_every_request_that_led_to_the_image(saved_panel):
    tab, db = saved_panel
    _image_row(db, "img1", prompt="a cat")
    _request_made(db, "img1", answered="Took the hat off.")
    image = _image_row(db, "img2", prompt="a cat, a scarf")
    _request_made(db, "img2", source="img1", asked="a scarf", answered="Gave the cat a scarf.")

    tab.show_saved_generation(image, [image])

    assert tab._param_form.request_exchange().turns() == [
        ("no hat", "Took the hat off."), ("a scarf", "Gave the cat a scarf.")]


def test_an_image_a_request_is_still_making_shows_the_exchange_in_the_request_section(
        saved_panel):
    tab, db = saved_panel
    running = _image_being_made(db, "img1", prompt="a cat")
    _request_made(db, "img1")

    tab.show_running_generation(running)

    assert tab._param_form.request_exchange().turns() == [("no hat", "Done.")]


def test_an_image_still_being_made_is_asked_no_change_of_until_it_lands(saved_panel):
    tab, db = saved_panel
    running = _image_being_made(db, "img1", prompt="a cat")
    _request_made(db, "img1")
    tab.show_running_generation(running)
    exchange = tab._param_form.request_exchange()
    assert not exchange._line.isEnabled()

    db.update_generation("img1", status="completed", output_files=json.dumps(
        [{"filename": "sdxl_img1.png", "subfolder": "image"}]))
    landed = db.get_generation("img1")
    tab.show_completed_result(landed, [landed])

    assert exchange._line.isEnabled()
    assert exchange.turns() == [("no hat", "Done.")]


def test_an_image_a_request_is_still_making_shows_the_requests_change_on_its_entry(
        saved_panel):
    tab, db = saved_panel
    running = _image_being_made(db, "img1", prompt="a cat")
    _request_made(db, "img1")

    tab.show_running_generation(running)

    (entry,) = tab._param_form.request_exchange()._entries()
    struck, lit = _struck_and_lit_in(entry.tip)
    assert "a hat" in struck
    assert "hat" in lit
    assert _positive(tab) == "a cat"
    assert _message(tab) == ""


def test_an_image_a_request_is_still_making_links_to_the_one_it_was_asked_of(saved_panel):
    tab, db = saved_panel
    _image_row(db, "src", prompt="a cat, a hat")
    running = _image_being_made(db, "img1", prompt="a cat")
    _request_made(db, "img1", source="src")

    tab.show_running_generation(running)

    section = tab._related._requests
    assert not section.isHidden()
    assert [(tile.heading, tile._prompt_id)
            for tile in section.findChildren(SourceTile)] == [("Requested from", "src")]


def test_hovering_the_request_that_made_an_image_shows_the_whole_prompts_with_its_change(
        saved_panel):
    tab, db = saved_panel
    image = _image_row(db, "img1", prompt="a cat")
    _request_made(db, "img1")

    tab.show_saved_generation(image, [image])

    (entry,) = tab._param_form.request_exchange()._entries()
    tip = entry.tip
    struck, lit = _struck_and_lit_in(tip)
    assert ("a cat" in tip)
    assert ("blurry" in tip)
    assert "Positive Prompt" in tip
    assert "a hat" in struck
    assert "hat" in lit


def _thumbnail_of(db, prompt_id, tmp_path):
    image = QImage(30, 20, QImage.Format.Format_RGB32)
    image.fill(Qt.GlobalColor.gray)
    path = tmp_path / f"{prompt_id}_thumb.png"
    image.save(str(path))
    db.update_generation(prompt_id, thumbnail_path=str(path))
    return str(path)


def test_hovering_the_request_shows_the_image_it_was_asked_of_beside_the_one_it_made(
        saved_panel, tmp_path):
    tab, db = saved_panel
    _image_row(db, "src", prompt="a cat, a hat")
    image = _image_row(db, "img1", prompt="a cat")
    _request_made(db, "img1", source="src")
    asked_of, made = _thumbnail_of(db, "src", tmp_path), _thumbnail_of(db, "img1", tmp_path)

    tab.show_saved_generation(db.get_generation("img1"), [image])

    (entry,) = tab._param_form.request_exchange()._entries()
    assert entry.tip.index(asked_of) < entry.tip.index(made)


def test_a_request_asked_of_the_image_on_display_shows_that_image_before_it(
        saved_panel, qtbot, monkeypatch, tmp_path):
    _rewriting(monkeypatch)
    tab, db = saved_panel
    image = _image_row(db, "img1", prompt="a woman on a couch")
    shown = _thumbnail_of(db, "img1", tmp_path)
    tab.show_saved_generation(db.get_generation("img1"), [image])

    exchange = _ask(tab, qtbot, "two women")
    qtbot.waitUntil(lambda: exchange.turns() == [("two women", "Done.")], timeout=5000)

    (entry,) = exchange._entries()
    assert shown in entry.tip


def test_an_image_a_request_made_has_its_prompt_fields_marked_like_any_other_images(
        saved_panel, qtbot):
    tab, db = saved_panel
    image = _image_row(db, "img1", prompt="a cat")
    _request_made(db, "img1")

    tab.show_saved_generation(image, [image])

    positive = _positive_field(tab)
    assert _struck_and_lit(positive) == ("", "")
    assert _positive(tab) == "a cat"
    assert _message(tab) == ""


def test_generate_on_a_request_leaves_what_the_request_changed_marked(saved_panel, qtbot):
    tab, db = saved_panel
    image = _image_row(db, "img1", prompt="a cat")
    _request_made(db, "img1")
    tab.show_saved_generation(image, [image])
    (entry,) = tab._param_form.request_exchange()._entries()
    assert "a hat" in _struck_and_lit_in(entry.tip)[0]

    tab._on_generate()

    (entry,) = tab._param_form.request_exchange()._entries()
    assert "a hat" in _struck_and_lit_in(entry.tip)[0]
    assert _struck_and_lit(_positive_field(tab)) == ("", "")


def test_the_requests_change_to_each_scene_of_a_video_shows_on_its_entry(saved_panel):
    tab, db = saved_panel
    before = story_of(["a dog running", "a dog asleep"])
    after = story_of(["a dog running, grass", "a dog asleep, grass"])
    video = _video_row(db, positive_prompt=after, scene_frames=[81, 81], frame_count=161)
    db.record_request(NewRequest(prompt_id="vid1", source_prompt_id="src", heard="", asked="more grass",
                      old_positive=before, old_negative=""))
    db.requests.record_turns("vid1", [Turn("more grass", "Grass under both.", before, "", after, "")])

    tab.show_saved_generation(video, [])

    (entry,) = tab._param_form.request_exchange()._entries()
    _struck, lit = _struck_and_lit_in(entry.tip)
    assert lit.count("grass") == 2


def test_any_image_on_display_can_be_asked_a_change_of(saved_panel):
    tab, db = saved_panel
    image = _image_row(db, "img1", prompt="a cat")

    tab.show_saved_generation(image, [image])

    exchange = tab._param_form.request_exchange()
    assert exchange.turns() == []
    assert exchange._line.isEnabled()


def test_a_tab_showing_nothing_has_nothing_to_ask_a_change_of(tab):
    assert not tab._param_form.request_exchange()._line.isEnabled()


def test_asking_rewrites_the_prompts_of_the_image_on_display_and_shows_the_models_sentence(
        saved_panel, qtbot, monkeypatch):
    calls = _rewriting(monkeypatch)
    tab, db = saved_panel
    image = _image_row(db, "img1", prompt="a woman on a couch")
    tab.show_saved_generation(image, [image])

    exchange = _ask(tab, qtbot, "two women")

    qtbot.waitUntil(lambda: _positive(tab) == "two women on a couch", timeout=5000)
    assert [(positive, words) for positive, _negative, words in calls] == [
        ("a woman on a couch", "two women")]
    assert exchange.turns() == [("two women", "Done.")]
    assert exchange._status.isHidden()
    assert exchange._line.text() == ""
    assert _message(tab) == "(not yet generated with modifications)"


def test_a_requests_rewrite_of_the_image_on_display_lands_in_boxes_of_whole_words(
        saved_panel, qtbot, monkeypatch, tmp_path):
    monkeypatch.setattr(config, "COMFYUI_DIR", tmp_path / "ComfyUI")
    clip_reader(tmp_path / "ComfyUI")
    cats = [" ".join(["cat"] * count) for count in (80, 75, 5)]
    _rewriting(monkeypatch, answer=(cats[0], "blurry"))
    tab, db = saved_panel
    image = _image_row(db, "img1", prompt="a woman on a couch")
    tab.show_saved_generation(image, [image])

    _ask(tab, qtbot, "eighty cats")

    qtbot.waitUntil(lambda: _positive(tab) == f"{cats[1]}{BOX_BREAK}{cats[2]}", timeout=5000)


def test_a_request_about_a_setting_changes_it_on_the_form_and_the_turn_shows_the_change(
        saved_panel, qtbot, monkeypatch):
    _rewriting(monkeypatch, answer=("a woman on a couch", "blurry"), changes={"steps": "30"})
    tab, db = saved_panel
    image = _image_row(db, "img1", prompt="a woman on a couch")
    tab.show_saved_generation(image, [image])

    exchange = _ask(tab, qtbot, "fewer steps")

    qtbot.waitUntil(lambda: tab.current_config().params.get("steps") == 30, timeout=5000)
    assert _positive(tab) == "a woman on a couch"
    (entry,) = exchange._entries()
    assert "Steps" in entry.tip
    assert "30" in entry.tip
    assert tab.asked()["turns"][0].changes() == [("Steps", "50", "30")]


def test_a_second_request_builds_on_the_first_and_generate_records_every_turn(
        saved_panel, qtbot, monkeypatch):
    calls = _rewriting(monkeypatch, answer=[("two women on a couch", "blurry"),
                                            ("two women on a beach", "blurry")])
    tab, db = saved_panel
    image = _image_row(db, "img1", prompt="a woman on a couch")
    tab.show_saved_generation(image, [image])
    _ask(tab, qtbot, "two women")
    qtbot.waitUntil(lambda: _positive(tab) == "two women on a couch", timeout=5000)

    _ask(tab, qtbot, "on a beach")

    qtbot.waitUntil(lambda: _positive(tab) == "two women on a beach", timeout=5000)
    assert [(positive, words) for positive, _negative, words in calls] == [
        ("a woman on a couch", "two women"), ("two women on a couch", "on a beach")]
    asked = tab.asked()
    assert [(turn.said, turn.answered) for turn in asked["turns"]] == [
        ("two women", "Done."), ("on a beach", "Done.")]
    assert asked["turns"][1].old_positive == "two women on a couch"
    assert (asked["asked"], asked["source_prompt_id"], asked["old_positive"]) == (
        "on a beach", "img1", "a woman on a couch")


class _NeverAnswers:
    def ask(self, *args, **settings):
        pass


def test_the_line_waits_while_the_model_works_out_a_request(saved_panel, qtbot):
    tab, db = saved_panel
    image = _image_row(db, "img1", prompt="a cat")
    tab.show_saved_generation(image, [image])
    tab._requests = _NeverAnswers()

    exchange = _ask(tab, qtbot, "a hat")

    assert not exchange._line.isEnabled()
    assert exchange._status.text() == "updating…"
    assert tab.asked() is None


def test_words_that_ask_for_nothing_say_so_and_come_off_the_exchange(saved_panel, qtbot, monkeypatch):
    _rewriting(monkeypatch)
    tab, db = saved_panel
    image = _image_row(db, "img1", prompt="a cat")
    tab.show_saved_generation(image, [image])

    exchange = _ask(tab, qtbot, "please")

    qtbot.waitUntil(lambda: "couldn't" in exchange._status.text(), timeout=5000)
    assert exchange.turns() == []
    assert _positive(tab) == "a cat"
    assert tab.asked() is None


def test_an_answer_to_a_request_since_superseded_is_dropped(saved_panel, monkeypatch):
    _rewriting(monkeypatch)
    tab, db = saved_panel
    image = _image_row(db, "img1", prompt="a cat")
    tab.show_saved_generation(image, [image])

    tab._on_rewritten((tab._asked + 1, "img1"), ("an old answer", ""))

    assert _positive(tab) == "a cat"


def test_a_request_changes_each_scene_of_a_video_told_in_scenes(saved_panel, qtbot, monkeypatch):
    _rewriting(monkeypatch, answer=RuntimeError("no model here"))
    tab, db = saved_panel
    video = _video_row(db, positive_prompt=story_of(["a dog running", "a dog asleep"]),
                       scene_frames=[81, 81], frame_count=161)
    tab.show_saved_generation(video, [])

    _ask(tab, qtbot, "more grass")

    scenes = tab._param_form._widgets["positive_prompt"]
    qtbot.waitUntil(lambda: [diff_text.live_text(field) for field in scenes.fields("positive_prompt")]
                    == ["a dog running, grass", "a dog asleep, grass"], timeout=5000)


def _completed_generation(db, workflow_name, params):
    db.insert_generation(NewGeneration(
        prompt_id="done", workflow_name=workflow_name,
        workflow_version=WORKFLOW_REGISTRY[workflow_name].version,
        positive_prompt=params.get("positive_prompt", ""), negative_prompt="",
        seed=params.get("seed"), params_json=json.dumps(params), workflow_json="{}",
    ))
    db.update_generation("done", status="completed", output_files=json.dumps(
        [{"filename": "sdxl_t2i_done.png", "subfolder": "image"}]))


def test_generate_says_it_will_draw_a_random_seed_over_a_finished_run(tab, qtbot):
    wf = WORKFLOW_REGISTRY["sdxl_t2i"]
    params = dict(wf.default_params(), positive_prompt="a cat", seed=42)
    _completed_generation(tab._db, "sdxl_t2i", params)

    tab.prefill("sdxl_t2i", params)

    qtbot.waitUntil(lambda: tab._generate_btn.text() == "Generate with Random seed")
    assert "already been generated" in tab._generate_btn.toolTip()


def test_a_video_back_on_its_own_seeds_says_generate_will_draw_a_random_seed(saved_panel,
                                                                           qtbot):
    tab, db = saved_panel
    tab.show_saved_generation(_video_row(db, input_image="frame.png [output]", noise_seed=22, audio_seed=33), [])

    for key in ("noise_seed", "audio_seed"):
        tab._param_form._randomize_checks[key].click()

    assert _message(tab) == ""
    qtbot.waitUntil(lambda: tab._generate_btn.text() == "Generate with Random seed")


def test_a_video_just_clicked_says_generate_will_draw_a_random_seed(saved_panel, qtbot):
    tab, db = saved_panel

    tab.show_saved_generation(
        _video_row(db, input_image="frame.png [output]", noise_seed=22, audio_seed=33), [])

    assert tab._param_form.seed_is_random()
    qtbot.waitUntil(lambda: tab._generate_btn.text() == "Generate with Random seed")


def test_a_tab_on_an_imported_images_own_settings_says_generate_will_draw_a_random_seed(
        saved_panel, qtbot):
    tab, db = saved_panel
    params = dict(WORKFLOW_REGISTRY["sdxl_t2i"].default_params(), positive_prompt="a cat",
                  seed=1)
    db.insert_generation(NewGeneration(prompt_id="imp", workflow_name="sdxl_t2i", workflow_version="v002",
                         positive_prompt="a cat", seed=1, params_json=json.dumps(params),
                         workflow_json="{}", source=GenerationSource.IMPORTED))
    db.update_generation("imp", status="completed", output_files=json.dumps(
        [{"filename": "imp.png", "subfolder": "image"}]))

    tab.show_saved_generation(db.get_generation("imp"), [])

    assert _message(tab) == ""
    qtbot.waitUntil(lambda: tab._generate_btn.text() == "Generate with Random seed")


def test_editing_the_settings_takes_the_random_seed_caption_back_off(tab, qtbot):
    wf = WORKFLOW_REGISTRY["sdxl_t2i"]
    params = dict(wf.default_params(), positive_prompt="a cat", seed=42)
    _completed_generation(tab._db, "sdxl_t2i", params)
    tab.prefill("sdxl_t2i", params)
    qtbot.waitUntil(lambda: tab._generate_btn.text() == "Generate with Random seed")

    tab._param_form.set_values({"positive_prompt": "a dog"})

    qtbot.waitUntil(lambda: tab._generate_btn.text() == "Generate")
    assert tab._generate_btn.toolTip() == ""


@pytest.mark.parametrize(("key", "picked"), [("sampler_name", "euler_ancestral"),
                                         ("scheduler", "karras")])
def test_a_run_that_lands_after_its_tab_was_changed_leaves_generate_on_the_shown_seed(
        tab, qtbot, key, picked):
    wf = WORKFLOW_REGISTRY["sdxl_t2i"]
    params = dict(wf.default_params(), positive_prompt="a cat", seed=42)
    tab.prefill("sdxl_t2i", params)
    _completed_generation(tab._db, "sdxl_t2i", params)

    tab._param_form._widgets[key].setCurrentText(picked)
    tab.show_completed_result(tab._db.get_generation("done"), [])

    qtbot.wait(generate_tab_module._CAPTION_DELAY_MS * 3)
    assert tab._generate_btn.text() == "Generate"
    assert _message(tab) == "(not yet generated with modifications)"


_FOLDER_KEY = "image/sdxl_t2i/abcdef123456"
_FOLDER_LABEL = "AB12CD34"


def _folder_params(prompt="a cat on a couch"):
    return dict(WORKFLOW_REGISTRY["sdxl_t2i"].default_params(),
                positive_prompt=prompt, negative_prompt="blurry", seed=7)


def _images(tmp_path, count):
    paths = []
    for n in range(count):
        path = tmp_path / f"folder_{n}.png"
        Image.new("RGB", (12, 9), (30 * n, 90, 140)).save(path)
        paths.append(str(path))
    return paths


@pytest.fixture
def modify_batch_tab(blank_panel, tmp_path):
    blank_panel.open_modify_batch(_FOLDER_KEY, _FOLDER_LABEL, "sdxl_t2i",
                                  _folder_params(), _images(tmp_path, 3))
    return blank_panel


def _positive_field(tab):
    return tab._param_form._widgets["positive_prompt"].boxes()[0]


def test_a_tab_asking_for_changes_to_a_folder_has_no_dropdown_of_how_many(modify_batch_tab):
    assert modify_batch_tab._how_many.isHidden()

    modify_batch_tab.prefill("sdxl_t2i", _folder_params())

    assert not modify_batch_tab._how_many.isHidden()


def _top_right_corner(widget):
    corner = widget.mapTo(widget.window(), widget.rect().topRight())
    return widget.window().grab().toImage().pixelColor(corner.x(), corner.y())


def test_generate_keeps_rounded_corners_with_its_dropdown_and_without(modify_batch_tab, app_chrome):
    modify_batch_tab.show()
    QApplication.processEvents()
    pair = modify_batch_tab._generate_btn.parentWidget()
    assert _top_right_corner(pair) == BG_PRIMARY

    modify_batch_tab.prefill("sdxl_t2i", _folder_params())
    QApplication.processEvents()

    assert _top_right_corner(pair) == BG_PRIMARY


def _modify_batch(count=3, label=_FOLDER_LABEL, opened_on=None):
    return modify_batch_module.ModifyBatch(
        folder_key=_FOLDER_KEY, label=label, count=count,
        opened_on=opened_on or ConfigSnapshot("sdxl_t2i", _folder_params(), False))


def test_a_modify_batch_names_itself_after_the_folder_it_asks_about():
    assert _modify_batch().title() == f"Modify batch {_FOLDER_LABEL}"


def test_a_modify_batch_counts_its_runs_in_the_hover_rather_than_on_the_button():
    assert _modify_batch(count=3).caption() == "Modify batch (all seeds)"
    assert "all 3 images" in _modify_batch(count=3).tooltip()


def test_a_one_image_folder_gets_wording_of_its_own():
    tooltip = _modify_batch(count=1).tooltip()
    assert "one image" in tooltip
    assert "1 image" not in tooltip


def test_a_modify_batch_knows_whether_anything_has_actually_been_rewritten():
    opened_on = ConfigSnapshot("sdxl_t2i", _folder_params(), False)
    request = _modify_batch(opened_on=opened_on)

    assert request.is_unchanged(ConfigSnapshot("sdxl_t2i", _folder_params(), False))
    assert not request.is_unchanged(
        ConfigSnapshot("sdxl_t2i", _folder_params(prompt="a dog on a couch"), False))


def test_a_modify_batch_cannot_be_edited_after_the_tab_opens_on_it():
    try:
        _modify_batch().count = 9
    except FrozenInstanceError:
        return
    pytest.fail(
        "what the tab opened on is how a press tells a rewrite from a re-run; one that could "
        "be edited could quietly come to agree with whatever was typed after it")


def test_a_modify_batch_tab_shows_the_whole_folder_in_its_preview(modify_batch_tab):
    preview = modify_batch_tab._viewport
    assert (preview._stack.currentWidget() is preview._sheet, preview._sheet.count()) == (True, 3), (
        "a rewrite lands on every item in the folder, so the preview has to be every item: "
        "showing the newest one alone would say the edit was about that item")


def test_the_press_asks_for_changes_and_counts_them_in_the_hover(modify_batch_tab):
    assert modify_batch_tab._generate_btn.text() == "Modify batch (all seeds)"
    assert "all 3 images" in modify_batch_tab._generate_btn.toolTip()


def test_every_prompt_is_marked_against_what_it_says_now(modify_batch_tab):
    fields = modify_batch_tab._param_form.text_fields()
    assert all(w.findChildren(_Tracker) for w in fields)
    assert {w.toPlainText() for w in fields} == {"a cat on a couch", "blurry"}


def test_the_tab_is_named_after_the_folder_it_asks_about(modify_batch_tab):
    assert modify_batch_tab.title() == f"Modify batch {_FOLDER_LABEL}"


def test_a_modify_batch_tab_offers_no_corners_over_its_wall_of_images(
        saved_panel, tmp_path, monkeypatch):
    tab, db = saved_panel
    image = _image_row(db, "img1")
    monkeypatch.setattr(generate_tab_module, "resolve_preview",
                        lambda row, out: (Path("C:/out/img1.png"), "image"))
    tab.show_saved_generation(image, [image])
    assert tab._viewport._actions_id == "img1"
    fired = []
    tab.item_action_requested.connect(lambda pid, action: fired.append(pid))

    tab.open_modify_batch(_FOLDER_KEY, _FOLDER_LABEL, "sdxl_t2i",
                          _folder_params(), _images(tmp_path, 3))

    assert tab._viewport._actions_id is None
    tab._viewport._on_control("trash")
    assert fired == []


def test_a_settings_push_does_not_re_arm_the_corners_over_a_wall(modify_batch_tab):
    modify_batch_tab.set_enhance_settings(gallery.EnhanceSettings(auto=True))

    assert modify_batch_tab._viewport._actions_id is None


def test_a_settings_push_does_not_arm_corners_over_a_followed_runs_frames(
        saved_panel, tmp_path):
    tab, db = saved_panel
    image = _image_row(db, "img1")
    tab.show_saved_generation(image, [image])
    tab.show_live_frame(_frame_bytes(tmp_path))

    tab.set_enhance_settings(gallery.EnhanceSettings(auto=True))

    assert tab._viewport.actions_id() is None


def test_an_enhancement_streaming_into_the_preview_keeps_its_corners(
        saved_panel, tmp_path):
    tab, db = saved_panel
    image = _image_row(db, "img1")
    tab.show_saved_generation(image, [image])

    tab.set_pending_enhancement(RunningEnhancement("running", _frame_bytes(tmp_path), "2x"))

    assert tab._viewport.actions_id() == "img1"


def test_a_modify_batch_tab_holds_no_generation_of_its_own(modify_batch_tab):
    assert modify_batch_tab.displayed_row() is None
    assert modify_batch_tab._displayed_config is None


def test_generate_asks_for_the_folder_rather_than_these_settings(modify_batch_tab, qtbot):
    _positive_field(modify_batch_tab).setPlainText("a dog on a couch")

    with qtbot.waitSignal(modify_batch_tab.modify_batch_requested) as caught:
        modify_batch_tab._generate_btn.click()

    folder_key, workflow_name, params = caught.args
    assert folder_key == _FOLDER_KEY
    assert workflow_name == "sdxl_t2i"
    assert params["positive_prompt"] == "a dog on a couch"


def test_modify_batch_takes_the_red_and_green_off_its_prompts(modify_batch_tab, qtbot):
    _each_press_launches_a_run(modify_batch_tab)
    field = _positive_field(modify_batch_tab)
    field.setPlainText("a dog on a couch")
    qtbot.waitUntil(lambda: _struck_and_lit(field) == ("cat", "dog"), timeout=5000)

    modify_batch_tab._generate_btn.click()

    assert _struck_and_lit(field) == ("", "")
    assert field.toPlainText() == "a dog on a couch"


def test_a_canceled_modify_batch_marks_its_prompts_against_the_folder_again(modify_batch_tab, qtbot):
    _each_press_launches_a_run(modify_batch_tab)
    field = _positive_field(modify_batch_tab)
    field.setPlainText("a dog on a couch")
    modify_batch_tab._generate_btn.click()

    modify_batch_tab.forget_launched()

    assert _struck_and_lit(field) == ("cat", "dog")


def test_a_modify_batch_that_asked_for_nothing_says_so_instead_of_re_running_the_folder(
        modify_batch_tab, qtbot):
    fired = []
    modify_batch_tab.modify_batch_requested.connect(lambda *a: fired.append(a))

    modify_batch_tab._generate_btn.click()

    assert fired == []
    assert modify_batch_tab._generate_btn.text() == "Rewrite the prompt first"


def test_a_modify_batch_whose_prompt_has_an_unpaired_parenthesis_asks_to_resolve_it(modify_batch_tab):
    fired = []
    modify_batch_tab.modify_batch_requested.connect(lambda *a: fired.append(a))
    modify_batch_tab._param_form.set_values({"positive_prompt": "a (dog"})

    modify_batch_tab._generate_btn.click()

    assert fired == []
    assert modify_batch_tab._generate_btn.text() == "Resolve parentheses first"


def test_showing_a_generation_ends_the_modify_batch(modify_batch_tab, tmp_path):
    row = {"prompt_id": "p1", "workflow_name": "sdxl_t2i",
           "params_json": json.dumps(_folder_params()), "output_files": "[]"}

    modify_batch_tab.show_saved_generation(row, [])

    assert modify_batch_tab._modify_batch is None
    assert modify_batch_tab._generate_btn.text() == "Generate"


def test_ending_the_modify_batch_leaves_the_prompts_their_undo(modify_batch_tab, qtbot):
    modify_batch_tab._end_modify_batch()
    field = _positive_field(modify_batch_tab)

    field.setPlainText("a dog on a couch")
    qtbot.keyClick(field, Qt.Key.Key_Z, Qt.KeyboardModifier.ControlModifier)

    assert modify_batch_tab._param_form._widgets["positive_prompt"].value() == "a cat on a couch"


def test_picking_another_workflow_ends_the_modify_batch(modify_batch_tab):
    modify_batch_tab._workflow_dropdown.setCurrentIndex(_dropdown_index(modify_batch_tab, "flux_t2i_upscaled"))

    assert modify_batch_tab._generate_btn.text() == "Generate"


def test_a_landed_run_does_not_take_the_wall_of_images_away(modify_batch_tab):
    row = {"prompt_id": "p1", "workflow_name": "sdxl_t2i",
           "params_json": json.dumps(_folder_params()), "output_files": "[]"}

    modify_batch_tab.show_completed_result(row, [])

    assert modify_batch_tab.displayed_row() is None
    assert modify_batch_tab._viewport._stack.currentWidget() is modify_batch_tab._viewport._sheet



def _lanes():
    return list(export_lane_module.EXPORT_LANES)


_LOOP = "wan22_flf2v_loop"


def _lane_video(db, lane, prompt_id="vid1"):
    return _video_row(db, prompt_id,
                      workflow_name=_LOOP if lane.carries_loops else "wan22_i2v")


def _lane_offers(tab):
    names = tuple(f" {lane.name}" for lane in _lanes())
    return [re.sub(r"^<img[^>]*>&nbsp;", "\u2713 ", widget.text())
            for widget in tab.findChildren((QPushButton, QLabel))
            if widget.isVisibleTo(tab) and widget.text().endswith(names)]


@pytest.mark.parametrize(("workflow", "offer"), [(_LOOP, "→ Send to Genau"),
                                                 ("wan22_i2v", "→ Send to Kino"),
                                                 ("unknown", "→ Send to Kino")])
def test_a_loop_is_offered_to_genau_and_any_other_video_to_kino_alone(
        saved_panel, monkeypatch, workflow, offer):
    tab, db = saved_panel
    monkeypatch.setattr(generate_tab_module, "resolve_preview",
                        lambda row, out: (Path("C:/out/vid1.mp4"), "video"))

    tab.show_saved_generation(_video_row(db, "vid1", workflow_name=workflow), [])

    assert _lane_offers(tab) == [offer]


def test_the_kino_lanes_button_says_where_its_video_ends_up():
    assert export_lane_module.KINO.tooltip == (
        "Send this video down the Kino lane: Evolver sorts and upscales it on its usual "
        "schedule, then files it where Kino plays it.")


def _press(tab, caption):
    (button,) = [button for button in tab.findChildren(QPushButton)
                 if button.isVisibleTo(tab) and button.text() == caption]
    button.click()


def test_a_loop_already_sent_to_kino_offers_that_copy_back_before_genau(saved_panel,
                                                                         monkeypatch):
    tab, db = saved_panel
    _video_row(db, "vid1", workflow_name=_LOOP)
    db.mark_evolver_exported("vid1")
    monkeypatch.setattr(generate_tab_module, "resolve_preview",
                        lambda row, out: (Path("C:/out/vid1.mp4"), "video"))
    tab.show_saved_generation(db.get_generation("vid1"), [])
    assert _lane_offers(tab) == ["✓ Sent to Kino"]

    _press(tab, "Unsend")

    assert _lane_offers(tab) == ["→ Send to Genau"]


def test_a_loop_in_both_lanes_offers_its_kino_copy_back_and_then_its_genau_one(
        saved_panel, monkeypatch):
    tab, db = saved_panel
    _video_row(db, "vid1", workflow_name=_LOOP)
    db.mark_evolver_exported("vid1")
    db.mark_genau_exported("vid1")
    monkeypatch.setattr(generate_tab_module, "resolve_preview",
                        lambda row, out: (Path("C:/out/vid1.mp4"), "video"))
    tab.show_saved_generation(db.get_generation("vid1"), [])
    assert _lane_offers(tab) == ["✓ Sent to Kino"]

    _press(tab, "Unsend")

    assert _lane_offers(tab) == ["✓ Sent to Genau"]


def test_a_fresh_tab_offers_no_lane_at_all(saved_panel):
    tab, _db = saved_panel
    assert _lane_offers(tab) == []


@pytest.mark.parametrize("lane", _lanes(), ids=lambda lane: lane.name)
def test_a_lane_offers_itself_for_a_video_and_not_for_an_image(saved_panel,
                                                               monkeypatch, lane):
    tab, db = saved_panel

    monkeypatch.setattr(generate_tab_module, "resolve_preview",
                        lambda row, out: (Path("C:/out/vid1.mp4"), "video"))
    tab.show_saved_generation(_lane_video(db, lane), [])
    assert _lane_offers(tab) == [lane.send_caption]

    image = _image_row(db, "img1")
    monkeypatch.setattr(generate_tab_module, "resolve_preview",
                        lambda row, out: (Path("C:/out/img1.png"), "image"))
    tab.show_saved_generation(image, [image])
    assert _lane_offers(tab) == []


@pytest.mark.parametrize("lane", _lanes(), ids=lambda lane: lane.name)
def test_a_lane_copies_the_clip_into_its_own_folder_and_remembers_the_send(
        saved_panel, monkeypatch, lane):
    tab, db = saved_panel
    video_path = Path("C:/out/vid1.mp4")
    monkeypatch.setattr(generate_tab_module, "resolve_preview",
                        lambda row, out: (video_path, "video"))
    export = MagicMock(return_value=EVOLVER_INBOX_DIR / lane.source / "vid1.mp4")
    monkeypatch.setattr(evolver_export, "export_video", export)

    tab.show_saved_generation(_lane_video(db, lane), [])
    _press(tab, lane.send_caption)

    export.assert_called_once_with(video_path, EVOLVER_INBOX_DIR / lane.source,
                                   funscript=None)
    assert tab._displayed_row[lane.flag]
    assert _lane_offers(tab) == [f"✓ {lane.sent_caption}"]


@pytest.mark.parametrize(("lane", "brings_its_funscript"),
                         [(export_lane_module.KINO, True),
                          (export_lane_module.GENAU, False)],
                         ids=lambda value: getattr(value, "name", value))
def test_the_library_lane_sends_a_clip_with_its_funscript_and_the_genau_lane_alone(
        saved_panel, monkeypatch, lane, brings_its_funscript):
    tab, db = saved_panel
    video_path = Path("C:/out/vid1.mp4")
    funscript = Path("C:/out/funscript/vid1.funscript")
    monkeypatch.setattr(generate_tab_module, "resolve_preview",
                        lambda row, out: (video_path, "video"))
    monkeypatch.setattr(export_lane_module, "funscript_of",
                        lambda video, places: funscript if video == video_path else None)
    export = MagicMock(return_value=EVOLVER_INBOX_DIR / lane.source / "vid1.mp4")
    monkeypatch.setattr(evolver_export, "export_video", export)

    tab.show_saved_generation(_lane_video(db, lane), [])
    _press(tab, lane.send_caption)

    export.assert_called_once_with(video_path, EVOLVER_INBOX_DIR / lane.source,
                                   funscript=funscript if brings_its_funscript else None)


@pytest.mark.parametrize("lane", _lanes(), ids=lambda lane: lane.name)
def test_a_lane_lands_the_clip_in_the_inbox_this_panel_was_handed(
        qtbot, tmp_path, monkeypatch, lane):
    db = Database(tmp_path / "t.db")
    inbox = tmp_path / "somebody elses inbox"
    tab = GenerateTab(ComfyUIClient(folders=SUITE_FOLDERS), db,
                                inbox=evolver_export.EvolverInbox(inbox))
    qtbot.addWidget(tab)
    tab._viewport.show_media = MagicMock()
    video = tmp_path / "vid1.mp4"
    video.write_bytes(b"pixels")
    monkeypatch.setattr(generate_tab_module, "resolve_preview", lambda row, out: (video, "video"))

    tab.show_saved_generation(_lane_video(db, lane), [])
    _press(tab, lane.send_caption)

    assert (inbox / lane.source / "vid1.mp4").read_bytes() == b"pixels"


def test_a_clip_sent_to_evolver_arrives_with_the_funscript_this_app_made_for_it(
        qtbot, tmp_path, monkeypatch):
    output = tmp_path / "output"
    video = output / "video" / "vid1.mp4"
    video.parent.mkdir(parents=True)
    video.write_bytes(b"pixels")
    write_funscript(funscript_path_for(video, places=OutputPlaces.in_one_folder(output)), [{"at": 0, "pos": 0}])
    monkeypatch.setattr(generate_tab_module, "OUTPUT_PLACES", OutputPlaces.in_one_folder(output))
    monkeypatch.setattr(generate_tab_module, "resolve_preview", lambda row, out: (video, "video"))
    db = Database(tmp_path / "t.db")
    inbox = tmp_path / "0_inbox"
    tab = GenerateTab(ComfyUIClient(folders=SUITE_FOLDERS), db,
                                inbox=evolver_export.EvolverInbox(inbox))
    qtbot.addWidget(tab)
    tab._viewport.show_media = MagicMock()

    tab.show_saved_generation(_video_row(db, "vid1"), [])
    _press(tab, export_lane_module.KINO.send_caption)

    lane = inbox / export_lane_module.KINO.source
    assert sorted(path.name for path in lane.iterdir()) == ["vid1.funscript", "vid1.mp4"]


@pytest.mark.parametrize("lane", _lanes(), ids=lambda lane: lane.name)
def test_a_lane_does_not_send_the_same_clip_twice(saved_panel, monkeypatch, lane):
    tab, db = saved_panel
    _lane_video(db, lane)
    lane.mark(db, "vid1")
    monkeypatch.setattr(generate_tab_module, "resolve_preview",
                        lambda row, out: (Path("C:/out/vid1.mp4"), "video"))
    export = MagicMock()
    monkeypatch.setattr(evolver_export, "export_video", export)

    tab.show_saved_generation(db.get_generation("vid1"), [])
    assert _lane_offers(tab) == [f"✓ {lane.sent_caption}"]
    tab._on_send(lane)

    export.assert_not_called()


@pytest.mark.parametrize("lane", _lanes(), ids=lambda lane: lane.name)
def test_a_lane_refuses_a_send_the_row_records_even_with_its_button_still_live(
        saved_panel, monkeypatch, lane):
    tab, db = saved_panel
    _lane_video(db, lane)
    monkeypatch.setattr(generate_tab_module, "resolve_preview",
                        lambda row, out: (Path("C:/out/vid1.mp4"), "video"))
    export = MagicMock()
    monkeypatch.setattr(evolver_export, "export_video", export)
    tab.show_saved_generation(db.get_generation("vid1"), [])
    assert _lane_offers(tab) == [lane.send_caption]

    lane.mark(db, "vid1")
    tab._displayed_row = db.get_generation("vid1")
    tab._on_send(lane)

    assert export.call_count == 0, (
        "a button is only as fresh as the last time it was drawn; the column is what "
        "survives a restart, so the row decides")


@pytest.mark.parametrize("lane", _lanes(), ids=lambda lane: lane.name)
def test_a_lane_says_so_loudly_when_the_copy_fails(saved_panel, monkeypatch, lane):
    tab, db = saved_panel
    monkeypatch.setattr(generate_tab_module, "resolve_preview",
                        lambda row, out: (Path("C:/out/vid1.mp4"), "video"))
    monkeypatch.setattr(evolver_export, "export_video",
                        MagicMock(side_effect=OSError("inbox unreachable")))
    warn = MagicMock()
    monkeypatch.setattr(generate_tab_module.QMessageBox, "warning", warn)

    tab.show_saved_generation(_lane_video(db, lane), [])
    _press(tab, lane.send_caption)

    warn.assert_called_once()
    assert warn.call_args.args[1] == f"Send to {lane.name} failed"
    assert not tab._displayed_row[lane.flag]


@pytest.mark.parametrize("lane", _lanes(), ids=lambda lane: lane.name)
def test_a_sent_video_says_so_beside_an_unsend_button(saved_panel, monkeypatch, lane):
    tab, db = saved_panel
    _lane_video(db, lane)
    lane.mark(db, "vid1")
    monkeypatch.setattr(generate_tab_module, "resolve_preview",
                        lambda row, out: (Path("C:/out/vid1.mp4"), "video"))

    tab.show_saved_generation(db.get_generation("vid1"), [])

    assert _lane_offers(tab) == [f"✓ Sent to {lane.name}"]
    assert [button.text() for button in tab.findChildren(QPushButton)
            if button.isVisibleTo(tab) and "Unsend" in button.text()] == ["Unsend"], (
        "a send is a file copied into another app's folders, so the only way back is a delete there")


@pytest.mark.parametrize("lane", _lanes(), ids=lambda lane: lane.name)
def test_pressing_unsend_takes_the_send_back_and_offers_it_again(saved_panel,
                                                                 monkeypatch, lane):
    tab, db = saved_panel
    _lane_video(db, lane)
    lane.mark(db, "vid1")
    monkeypatch.setattr(generate_tab_module, "resolve_preview",
                        lambda row, out: (Path("C:/out/vid1.mp4"), "video"))
    tab.show_saved_generation(db.get_generation("vid1"), [])

    _press(tab, export_lane_module.UNSEND_CAPTION)

    row = db.get_generation("vid1")
    assert row[lane.unsent_flag]
    assert not row[lane.flag]
    assert _lane_offers(tab) == [lane.send_caption]


@pytest.mark.parametrize("lane", _lanes(), ids=lambda lane: lane.name)
def test_a_withdrawn_clip_says_so_under_the_button_that_offers_it_again(
        saved_panel, monkeypatch, lane):
    tab, db = saved_panel
    _lane_video(db, lane)
    lane.mark(db, "vid1")
    lane.unmark(db, "vid1")
    monkeypatch.setattr(generate_tab_module, "resolve_preview",
                        lambda row, out: (Path("C:/out/vid1.mp4"), "video"))

    tab.show_saved_generation(db.get_generation("vid1"), [])

    assert _lane_offers(tab) == [lane.send_caption]
    assert tab._lane_button.toolTip() == lane.withdrawn_tooltip, (
        "withdrawn, the button reads as it does for a video never sent, and nothing else on the tab "
        "mentions the other app: the tooltip is the one place left to say the deletion was called off")


@pytest.mark.parametrize("lane", _lanes(), ids=lambda lane: lane.name)
def test_sending_again_before_the_delete_runs_calls_it_off(saved_panel,
                                                           monkeypatch, lane):
    tab, db = saved_panel
    _lane_video(db, lane)
    lane.mark(db, "vid1")
    monkeypatch.setattr(generate_tab_module, "resolve_preview",
                        lambda row, out: (Path("C:/out/vid1.mp4"), "video"))
    monkeypatch.setattr(evolver_export, "export_video", MagicMock())
    tab.show_saved_generation(db.get_generation("vid1"), [])
    _press(tab, export_lane_module.UNSEND_CAPTION)

    _press(tab, lane.send_caption)

    row = db.get_generation("vid1")
    assert row[lane.flag]
    assert not row[lane.unsent_flag], (
        "the deletion waits for the other app's next run, so a send made right after a "
        "withdrawal has to take the withdrawal back")


@pytest.mark.parametrize("lane", _lanes(), ids=lambda lane: lane.name)
def test_a_lane_will_not_take_back_a_send_the_row_does_not_record(saved_panel,
                                                                  monkeypatch, lane):
    tab, db = saved_panel
    _lane_video(db, lane)
    monkeypatch.setattr(generate_tab_module, "resolve_preview",
                        lambda row, out: (Path("C:/out/vid1.mp4"), "video"))
    tab.show_saved_generation(db.get_generation("vid1"), [])

    tab._on_unsend(lane)

    assert db.get_generation("vid1")[lane.unsent_flag] is None


@pytest.mark.parametrize("lane", _lanes(), ids=lambda lane: lane.name)
def test_a_press_does_what_the_button_said_and_not_its_opposite(saved_panel,
                                                                monkeypatch, lane):
    tab, db = saved_panel
    _lane_video(db, lane)
    monkeypatch.setattr(generate_tab_module, "resolve_preview",
                        lambda row, out: (Path("C:/out/vid1.mp4"), "video"))
    export = MagicMock()
    monkeypatch.setattr(evolver_export, "export_video", export)
    tab.show_saved_generation(db.get_generation("vid1"), [])
    lane.mark(db, "vid1")
    tab._displayed_row = db.get_generation("vid1")

    _press(tab, lane.send_caption)

    export.assert_not_called()
    assert db.get_generation("vid1")[lane.unsent_flag] is None


def test_every_lane_is_told_apart_by_its_folder_its_column_and_its_stamp():
    lanes = _lanes()
    assert len({lane.source for lane in lanes}) == len(lanes)
    assert len({lane.flag for lane in lanes}) == len(lanes)
    assert len({lane.unsent_flag for lane in lanes}) == len(lanes)
    assert [lane.source for lane in lanes] == [EVOLVER_SOURCE, GENAU_SOURCE]


def test_every_lane_stamps_a_column_the_database_actually_writes(saved_panel):
    _tab, db = saved_panel
    _video_row(db, "vid1")

    for lane in _lanes():
        lane.mark(db, "vid1")
        assert db.get_generation("vid1")[lane.flag]
        lane.unmark(db, "vid1")
        assert db.get_generation("vid1")[lane.unsent_flag]


def test_generate_is_off_while_its_folder_is_already_making_one(tab, qtbot):
    tab.set_making_one_check(
        lambda config: config.params["positive_prompt"] == "a folder making one")
    prompt = _positive_field(tab)

    prompt.setPlainText("a folder making one")
    assert tab._generate_btn.isEnabled() is False, (
        "the user's rule, one item at a time per folder: a second press made to be sure the first "
        "took used to make a second image nobody asked for")
    qtbot.waitUntil(lambda: "already making" in tab._generate_btn.toolTip())

    prompt.setPlainText("a folder of its own")
    assert tab._generate_btn.isEnabled() is True
    qtbot.waitUntil(lambda: tab._generate_btn.toolTip() == "")


@pytest.fixture
def recommended(monkeypatch):
    default = WORKFLOW_REGISTRY["sdxl_t2i"].default_params()["checkpoint"]
    models = {
        default: {"name": "Default Model", "samplers": {"euler_ancestral": ["normal"]},
                  "steps": [20, 40], "cfg": [3, 6],
                  "start": {"sampler_name": "euler_ancestral", "scheduler": "normal",
                            "steps": 30, "cfg": 4}},
        "example_other.safetensors": {
            "name": "Other Model", "samplers": {"dpmpp_2m": ["karras"]},
            "steps": [30, 40], "cfg": [3, 7],
            "start": {"sampler_name": "dpmpp_2m", "scheduler": "karras", "steps": 35, "cfg": 5}},
    }
    monkeypatch.setattr(advice_module, "model_recommendations", lambda: models)
    monkeypatch.setattr(
        model_dropdowns_module, "list_model_files",
        lambda category, fallback, **terms: (
            [*fallback, "example_other.safetensors"] if category == "checkpoints" else list(fallback)))
    return models


def _pick_model(tab, file_name):
    checkpoint = tab._param_form._widgets["checkpoint"]
    checkpoint.setCurrentIndex(checkpoint.findData(file_name))


def _drawing_settings(tab):
    values = tab._param_form.get_values()
    return values["sampler_name"], values["scheduler"], values["steps"], values["cfg"]


def test_a_fresh_image_starts_on_its_models_recommended_settings(blank_panel, recommended):
    blank_panel._workflow_dropdown.setCurrentIndex(_dropdown_index(blank_panel, "sdxl_t2i"))

    assert _drawing_settings(blank_panel) == ("euler_ancestral", "normal", 30, 4.0)


def test_picking_another_model_for_a_fresh_image_takes_that_models_settings(
        blank_panel, recommended):
    blank_panel._workflow_dropdown.setCurrentIndex(_dropdown_index(blank_panel, "sdxl_t2i"))

    _pick_model(blank_panel, "example_other.safetensors")

    assert _drawing_settings(blank_panel) == ("dpmpp_2m", "karras", 35, 5.0)


def test_picking_another_model_for_a_shown_image_keeps_its_settings(recommended, saved_panel):
    tab, db = saved_panel
    image = _image_row(db, "img1", prompt="a cat")
    tab.show_saved_generation(image, [image])
    shown = _drawing_settings(tab)

    _pick_model(tab, "example_other.safetensors")

    assert _drawing_settings(tab) == shown


def test_a_models_recommended_settings_stay_with_its_workflow(blank_panel, recommended):
    blank_panel._workflow_dropdown.setCurrentIndex(_dropdown_index(blank_panel, "sdxl_t2i"))

    blank_panel._workflow_dropdown.setCurrentIndex(_dropdown_index(blank_panel, "wan22_t2i"))

    values = blank_panel._param_form.get_values()
    defaults = WORKFLOW_REGISTRY["wan22_t2i"].default_params()
    assert (values["steps"], values["cfg"]) == (defaults["steps"], defaults["cfg"])


def test_a_setting_off_its_models_recommendation_shows_its_warning(blank_panel, recommended):
    blank_panel._workflow_dropdown.setCurrentIndex(_dropdown_index(blank_panel, "sdxl_t2i"))
    mark = blank_panel._param_form._warning_marks["steps"]
    assert mark.isHidden()

    blank_panel._param_form._widgets["steps"].setValue(80)

    assert not mark.isHidden()
    assert mark.toolTip() == "Default Model's page recommends 20\u201340 steps. Click to use 40."


def test_a_number_outside_its_good_range_shows_its_warning_with_no_page_to_judge_it(tab):
    mark = tab._param_form._warning_marks["steps"]
    assert mark.isHidden()

    tab._param_form._widgets["steps"].setValue(200)

    assert not mark.isHidden()
    assert mark.toolTip() == "Good range: 25\u201350. Click to use 50."


def test_a_settings_tooltip_says_the_range_its_models_page_holds_it_to(blank_panel, recommended):
    blank_panel._workflow_dropdown.setCurrentIndex(_dropdown_index(blank_panel, "sdxl_t2i"))

    tip = blank_panel._param_form._widgets["cfg"].toolTip()

    assert tip.endswith(" Default Model's page recommends 3\u20136.")


def test_picking_another_model_puts_its_range_in_the_tooltip(blank_panel, recommended):
    blank_panel._workflow_dropdown.setCurrentIndex(_dropdown_index(blank_panel, "sdxl_t2i"))

    _pick_model(blank_panel, "example_other.safetensors")

    tips = {key: blank_panel._param_form._widgets[key].toolTip() for key in ("steps", "cfg")}
    assert tips["steps"].endswith(" Other Model's page recommends 30\u201340 steps.")
    assert tips["cfg"].endswith(" Other Model's page recommends 3\u20137.")


def test_a_negative_prompt_grayed_at_prompt_strength_one_says_why(blank_panel):
    blank_panel._workflow_dropdown.setCurrentIndex(_dropdown_index(blank_panel, "krea2_t2i"))
    form = blank_panel._param_form

    form._widgets["cfg"].setValue(1.0)

    (field,), label = form._widgets["negative_prompt"].boxes(), form._labels["negative_prompt"]
    assert field.property("inert") is True
    assert field.toolTip() == label.toolTip() == STRENGTH_ONE_HELP


def _drawn_in(prompt) -> set[str]:
    colors = set()
    for field in prompt.boxes():
        cursor = QTextCursor(field.document())
        for position in range(1, len(field.toPlainText()) + 1):
            cursor.setPosition(position)
            own = cursor.charFormat().foreground()
            colors.add((own.color() if own.style() != Qt.BrushStyle.NoBrush
                        else field.palette().color(QPalette.ColorRole.Text)).name())
    return colors


@pytest.mark.parametrize(("made_at", "then", "drawn"), [(1.0, 5.0, TEXT_PRIMARY),
                                                   (5.0, 1.0, TEXT_MUTED)])
def test_a_shown_images_negative_prompt_is_gray_exactly_while_the_run_ignores_it(
        app_chrome, saved_panel, made_at, then, drawn):
    tab, db = saved_panel
    image = _image_row(db, negative_prompt="blurry, low quality", cfg=made_at)
    tab.show_saved_generation(image, [image])

    tab._param_form._widgets["cfg"].setValue(then)

    assert _drawn_in(tab._param_form._widgets["negative_prompt"]) == {drawn.name()}


def _on_screen(qtbot, tab):
    tab.resize(700, 1400)
    with qtbot.waitExposed(tab):
        tab.show()
    return tab


def test_clicking_a_sections_warning_leaves_no_warning_in_it(qtbot, blank_panel, recommended):
    blank_panel._workflow_dropdown.setCurrentIndex(_dropdown_index(blank_panel, "sdxl_t2i"))
    form = _on_screen(qtbot, blank_panel)._param_form
    form.set_values({"sampler_name": "dpmpp_2m", "scheduler": "normal", "steps": 80})
    calibration = form._sections["Calibration"].warning

    qtbot.mouseClick(calibration, Qt.MouseButton.LeftButton)

    assert calibration.isHidden()
    assert _drawing_settings(blank_panel)[:3] == ("euler_ancestral", "normal", 40)


def test_the_workflows_warning_carries_every_warning_and_resolves_them_all(
        qtbot, blank_panel, recommended):
    blank_panel._workflow_dropdown.setCurrentIndex(_dropdown_index(blank_panel, "sdxl_t2i"))
    form = _on_screen(qtbot, blank_panel)._param_form
    warning = blank_panel._workflow_warning
    assert warning.isHidden()

    form.set_values({"steps": 80, "cfg": 9.0})
    assert warning.toolTip() == (
        "Steps: 80. Default Model's page recommends 20\u201340 steps. Click to use 40.\n"
        "Prompt Strength: 9. Default Model's page recommends 3\u20136. Click to use 6.")
    qtbot.mouseClick(warning, Qt.MouseButton.LeftButton)

    assert warning.isHidden()
    assert _drawing_settings(blank_panel)[2:] == (40, 6.0)


def test_a_story_too_long_for_its_good_range_is_among_the_workflows_warnings(qtbot, blank_panel):
    blank_panel._workflow_dropdown.setCurrentIndex(_dropdown_index(blank_panel, "wan22_i2v"))
    form = _on_screen(qtbot, blank_panel)._param_form

    form.set_values({"scene_frames": [241], "frame_count": 241})
    assert "Scenes: 15 s. Good range: 5\u201310 s. Click to use 10 s." in (
        blank_panel._workflow_warning.toolTip().split("\n"))
    qtbot.mouseClick(blank_panel._workflow_warning, Qt.MouseButton.LeftButton)

    assert form.get_values()["frame_count"] == 161


_STYLE_SAID = ("Example Style 1.0's trigger word, exmplstyle, isn't in the Positive Prompt. "
               "Click to add it.")


@pytest.fixture
def worded_style(installed_models, worded_loras, titled_models):
    installed_models.add("loras", "example_style.safetensors", arch=KREA2, lora=True)
    worded_loras({"example_style": ["exmplstyle"]})
    titled_models({"example_style": "Example Style 1.0"})


def test_picking_a_lora_whose_trigger_word_the_prompt_lacks_warns_and_a_click_adds_it(
        qtbot, worded_style, blank_panel):
    blank_panel._workflow_dropdown.setCurrentIndex(_dropdown_index(blank_panel, "krea2_t2i"))
    form = _on_screen(qtbot, blank_panel)._param_form
    form._widgets["positive_prompt"].boxes()[0].setPlainText("a portrait")
    lora = form._widgets["lora"]

    lora.setCurrentIndex(lora.findData("example_style.safetensors"))

    assert form._warning_marks["lora"].toolTip() == _STYLE_SAID
    assert f"LoRA 1: Example Style 1.0. {_STYLE_SAID}" in (
        blank_panel._workflow_warning.toolTip().split("\n"))
    qtbot.mouseClick(form._warning_marks["positive_prompt"], Qt.MouseButton.LeftButton)
    assert form.get_values()["positive_prompt"] == "exmplstyle, a portrait"
    assert form._warning_marks["lora"].isHidden()


def test_a_prompt_that_tells_no_story_is_one_prompt_however_many_lines_of_dashes_it_holds(
        qtbot, worded_style, blank_panel):
    blank_panel._workflow_dropdown.setCurrentIndex(_dropdown_index(blank_panel, "krea2_t2i"))
    form = _on_screen(qtbot, blank_panel)._param_form
    form._widgets["positive_prompt"].boxes()[0].setPlainText(
        "exmplstyle, part one\n---\npart two")
    lora = form._widgets["lora"]

    lora.setCurrentIndex(lora.findData("example_style.safetensors"))

    assert form._warning_marks["lora"].isHidden()


def test_a_story_lacks_its_loras_trigger_word_in_a_scene_without_it_and_a_click_adds_it_there(
        qtbot, installed_models, worded_loras, blank_panel):
    installed_models.add("loras", "example_style.safetensors", arch=WAN, lora=True)
    worded_loras({"example_style": ["exmplstyle"]})
    blank_panel._workflow_dropdown.setCurrentIndex(_dropdown_index(blank_panel, "wan22_i2v"))
    form = _on_screen(qtbot, blank_panel)._param_form
    form.set_values({"positive_prompt": "scene one\n---\nexmplstyle, scene two",
                     "scene_frames": [81, 81], "lora_high": "example_style.safetensors"})

    qtbot.mouseClick(form._warning_marks["scene_frames"], Qt.MouseButton.LeftButton)

    assert form.get_values()["positive_prompt"] == (
        "exmplstyle, scene one\n---\nexmplstyle, scene two")


def test_the_workflows_warning_click_adds_the_first_of_a_loras_several_trigger_words(
        qtbot, installed_models, worded_loras, blank_panel):
    installed_models.add("loras", "example_actions.safetensors", arch=KREA2, lora=True)
    worded_loras({"example_actions": ["alpha", "beta"]})
    blank_panel._workflow_dropdown.setCurrentIndex(_dropdown_index(blank_panel, "krea2_t2i"))
    form = _on_screen(qtbot, blank_panel)._param_form
    form._widgets["positive_prompt"].boxes()[0].setPlainText("a portrait")
    lora = form._widgets["lora"]
    lora.setCurrentIndex(lora.findData("example_actions.safetensors"))

    qtbot.mouseClick(blank_panel._workflow_warning, Qt.MouseButton.LeftButton)

    assert form.get_values()["positive_prompt"] == "alpha, a portrait"


def test_a_shown_image_whose_prompt_left_off_its_loras_trigger_word_wears_the_warning(
        worded_style, saved_panel):
    tab, db = saved_panel
    params = dict(WORKFLOW_REGISTRY["krea2_t2i"].default_params(), positive_prompt="a cat",
                  lora="example_style.safetensors", seed=1)
    db.insert_generation(NewGeneration(prompt_id="img1", workflow_name="krea2_t2i", workflow_version="v001",
                         positive_prompt="a cat", seed=1, params_json=json.dumps(params),
                         workflow_json="{}"))
    db.update_generation("img1", status="completed",
                         output_files=json.dumps([{"filename": "krea_img1.png",
                                                   "subfolder": "image"}]))
    image = db.get_generation("img1")

    tab.show_saved_generation(image, [image])

    assert tab._param_form._warning_marks["positive_prompt"].toolTip() == _STYLE_SAID


def test_the_workflows_warning_sits_in_the_column_of_its_sections_rows_warnings(
        qtbot, blank_panel):
    blank_panel._workflow_dropdown.setCurrentIndex(_dropdown_index(blank_panel, "wan22_i2v"))
    tab = _on_screen(qtbot, blank_panel)

    def left(widget):
        return widget.mapTo(tab, QPoint(0, 0)).x()

    section = tab._param_form._sections["Workflow, Models & LoRAs"]
    assert section.content().isAncestorOf(tab._workflow_dropdown)
    marks = tab._param_form._warning_marks
    assert left(tab._workflow_warning) == left(marks["unet_high"])


def test_a_fresh_images_dropdowns_mark_what_its_models_page_recommends(blank_panel, recommended):
    blank_panel._workflow_dropdown.setCurrentIndex(_dropdown_index(blank_panel, "sdxl_t2i"))

    form = blank_panel._param_form
    marked = {key: {form._widgets[key].itemText(i) for i in range(form._widgets[key].count())
                    if form._widgets[key].itemIcon(i).cacheKey() == icons.thumbs_up_icon().cacheKey()}
              for key in ("sampler_name", "scheduler")}
    assert marked == {"sampler_name": {"euler_ancestral"}, "scheduler": {"normal"}}
def test_a_checkbox_clicked_on_the_tab_lands_on_the_shown_images_row(saved_panel):
    tab, db = saved_panel
    image = _image_row(db, "img9")
    db.set_actions("img9", MediaType.IMAGE, ItemActions(("alpha",)))
    tab.show_saved_generation(db.get_generation("img9"), [image])
    name = vocabulary(MediaType.IMAGE).checkboxes[0]

    tab._action.form().parentWidget().findChild(TickControl, action_checkbox(MediaType.IMAGE, name)).click()

    assert actions_of(db.get_generation("img9"), MediaType.IMAGE) == ItemActions(("alpha",), (name,))


def test_a_video_on_the_tab_lists_the_actions_it_was_set_with(saved_panel):
    tab, db = saved_panel
    _video_row(db, "vid9")
    db.set_actions("vid9", MediaType.VIDEO, ItemActions(("alpha", "beta")))

    tab.show_saved_generation(db.get_generation("vid9"), [])

    listed = tab._action.form().parentWidget().findChild(QWidget, action_pills(MediaType.VIDEO))
    assert (listed.parentWidget().isHidden(), [pill.text() for pill in listed.findChildren(Pill)]) == (
        False, ["alpha", "beta"])


def test_a_checkbox_clicked_on_the_tab_lands_on_the_shown_videos_row(saved_panel):
    tab, db = saved_panel
    tab.show_saved_generation(_video_row(db, "vid9"), [])
    name = vocabulary(MediaType.VIDEO).checkboxes[0]

    tab._action.form().parentWidget().findChild(TickControl, action_checkbox(MediaType.VIDEO, name)).click()

    assert actions_of(db.get_generation("vid9"), MediaType.VIDEO) == ItemActions((), (name,))


def test_the_image_zone_holds_a_dropped_item_and_leads_back_to_it(qtbot, tmp_path, monkeypatch,
                                                                  installed_models):
    output_dir = tmp_path / "output"
    (output_dir / "image").mkdir(parents=True)
    Image.new("RGB", (8, 8), (10, 20, 30)).save(output_dir / "image" / "sdxl_img1.png")
    monkeypatch.setattr(generate_tab_module, "OUTPUT_PLACES", OutputPlaces.in_one_folder(output_dir))
    db = Database(tmp_path / "t.db")
    _image_row(db, "img1", filename="sdxl_img1.png")
    tab = GenerateTab(ComfyUIClient(folders=SUITE_FOLDERS), db,
                       views=TabViews(names=ItemNames.from_library(db)))
    qtbot.addWidget(tab)
    tab._workflow_dropdown.setCurrentIndex(_dropdown_index(tab, "wan22_i2v"))
    zone = tab._param_form._widgets["input_image"]
    led_to = []
    tab.link_clicked.connect(led_to.append)

    mime = generation_mime("img1")
    zone.dropEvent(QDropEvent(QPointF(1, 1), Qt.DropAction.CopyAction, mime,
                              Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier))
    qtbot.mouseClick(zone, Qt.MouseButton.LeftButton)

    assert tab._param_form.get_values()["input_image"] == "image/sdxl_img1.png [output]"
    assert zone.toolTip() == tab._names.of("img1")
    assert led_to == ["img1"]


def test_a_second_lora_picked_on_a_tab_lowers_each_picked_strengths_good_range(
        qtbot, tmp_path, installed_models):
    for name in ("first_look.safetensors", "second_look.safetensors"):
        installed_models.add("loras", name, arch="krea2", lora=True)
    tab = GenerateTab(ComfyUIClient(folders=SUITE_FOLDERS),
                                Database(tmp_path / "test.db"))
    qtbot.addWidget(tab)
    tab._workflow_dropdown.setCurrentIndex(_dropdown_index(tab, "krea2_t2i"))
    form = tab._param_form
    mark = form._warning_marks["lora_strength"]

    form.set_values({"lora": "first_look.safetensors"})
    assert mark.isHidden()

    form.set_values({"lora_2": "second_look.safetensors"})
    assert not mark.isHidden()
    assert mark.toolTip() == "Good range while another LoRA is picked: 0.6\u20130.8. Click to use 0.8."
    assert form._widgets["lora_strength_2"].toolTip().endswith(
        " Good range while another LoRA is picked: 0.6\u20130.8.")


def test_a_tabs_lora_dropdown_says_when_its_picked_lora_was_trained(
        blank_panel, installed_models, titled_models):
    titled_models({"example_look": "Example Look 1.0"})
    installed_models.add("loras", "example_look.safetensors", arch="krea2", lora=True,
                         metadata={"ss_training_finished_at": "1792851468.891"})
    blank_panel._workflow_dropdown.setCurrentIndex(_dropdown_index(blank_panel, "krea2_t2i"))

    blank_panel._param_form.set_values({"lora": "example_look.safetensors"})

    assert blank_panel._param_form._widgets["lora"].toolTip().endswith(
        f"Trained {datetime.fromtimestamp(1792851468.891).astimezone():%Y-%m-%d %H:%M}.")


def _trainable_look(monkeypatch, tmp_path):
    folder = tmp_path / "pictures"
    folder.mkdir()
    (folder / "one.jpg").write_bytes(b"")
    monkeypatch.setattr(look_training, "load_content", lambda: {"trainable_loras": {"Example Look": {
        "pictures": str(folder), "base_model": "example_raw.safetensors",
        "text_encoder": "example_te.safetensors", "vae": "example_vae.safetensors"}}})
    monkeypatch.setattr(config, "LOOK_TRAINING_DIR", tmp_path / "lora training")


def test_a_tab_offers_to_retrain_a_lora_the_app_can_train_only_while_it_is_picked(
        blank_panel, monkeypatch, tmp_path, installed_models, titled_models):
    _trainable_look(monkeypatch, tmp_path)
    titled_models({"example_look": "Example Look 1.0"})
    installed_models.add("loras", "example_look.safetensors", arch="krea2", lora=True)
    blank_panel._workflow_dropdown.setCurrentIndex(_dropdown_index(blank_panel, "krea2_t2i"))
    controls = blank_panel._param_form.training.controls["lora"]
    assert controls.isHidden()
    asked = []
    blank_panel.train_requested.connect(asked.append)

    blank_panel._param_form.set_values({"lora": "example_look.safetensors"})

    assert not controls.isHidden()
    assert (controls.train.text(), controls.images.text()) == ("Retrain", "1 image")
    controls.train.click()
    assert asked == ["lora"]
    blank_panel.lora_offers.show_training("Example Look", "Training 10%")
    assert (controls.train.text(), controls.train.isEnabled()) == ("Training 10%", False)
    blank_panel.lora_offers.show_training("Example Look", None)
    assert (controls.train.text(), controls.train.isEnabled()) == ("Retrain", True)
    assert blank_panel.lora_value("lora") == "example_look.safetensors"

    blank_panel._param_form.set_values({"lora": NO_LORA})
    assert controls.isHidden()
    assert blank_panel.pick_lora("lora", "example_look.safetensors") is True
    assert not controls.isHidden()
    assert blank_panel.pick_lora("seed", "example_look.safetensors") is False


def test_a_sound_prompt_grays_the_words_past_where_its_reader_stops(
        blank_panel, tmp_path, monkeypatch):
    monkeypatch.setenv("HF_HUB_CACHE", str(tmp_path / "hub"))
    clap_reader(tmp_path / "hub")
    blank_panel._workflow_dropdown.setCurrentIndex(_dropdown_index(blank_panel, "wan22_i2v"))
    read = " ".join(["rain"] * 76)

    blank_panel._param_form.set_values({"audio_prompt": f"{read} on a tin roof"})

    (field,) = blank_panel._param_form._widgets["audio_prompt"].boxes()
    assert [(span.start, span.format.foreground().color().name())
            for span in field.document().firstBlock().layout().formats()] == [
        (len(read) + 1, TEXT_MUTED.name())]


class _OneTab:
    def __init__(self, tab):
        self._tab = tab

    def generate_tabs(self):
        return [self._tab]


@pytest.fixture
def look_in_two_versions(monkeypatch, tmp_path, installed_models, titled_models, worded_loras):
    _trainable_look(monkeypatch, tmp_path)
    titled_models({"look_one": "Example Look 1.0", "look_two": "Example Look 1.1"})
    worded_loras({"look_one": ["zzold"], "look_two": ["zznew"]})
    gone = installed_models.add("loras", "look_one.safetensors", arch="krea2", lora=True)
    installed_models.add("loras", "look_two.safetensors", arch="krea2", lora=True)
    return gone


def test_an_old_version_of_a_lora_offers_the_trash_where_the_newest_offers_retrain(
        blank_panel, look_in_two_versions):
    blank_panel._workflow_dropdown.setCurrentIndex(_dropdown_index(blank_panel, "krea2_t2i"))
    form = blank_panel._param_form
    controls = form.training.controls["lora"]

    form.set_values({"lora": "look_one.safetensors"})
    assert (controls.train.isHidden(), controls.trash.isHidden()) == (True, False)
    assert controls.trash.toolTip() == (
        "Moves Example Look 1.0 to the Recycle Bin. Example Look 1.1 stays.")
    assert controls.images.text() == "1 image"

    form.set_values({"lora": "look_two.safetensors"})
    assert (controls.train.isHidden(), controls.trash.isHidden()) == (False, True)
    assert controls.train.text() == "Retrain"


def test_a_training_under_way_shows_on_an_old_version_in_place_of_the_trash(
        blank_panel, look_in_two_versions):
    blank_panel._workflow_dropdown.setCurrentIndex(_dropdown_index(blank_panel, "krea2_t2i"))
    form = blank_panel._param_form
    controls = form.training.controls["lora"]
    form.set_values({"lora": "look_one.safetensors"})

    blank_panel.lora_offers.show_training("Example Look", "Training 10%")

    assert (controls.train.isHidden(), controls.trash.isHidden()) == (False, True)
    assert controls.train.text() == "Training 10%"


def test_the_trash_moves_the_tab_to_the_newest_version_and_its_trigger_word(
        blank_panel, look_in_two_versions):
    blank_panel._workflow_dropdown.setCurrentIndex(_dropdown_index(blank_panel, "krea2_t2i"))
    form = blank_panel._param_form
    form.set_values({"lora": "look_one.safetensors", "positive_prompt": "zzold, scene one"})
    LookTrainingController(None, info_tabs_of=lambda: _OneTab(blank_panel), parent=None,
                           trash=lambda _lora, _parent: look_in_two_versions.unlink() or True
                           ).wire(blank_panel)

    form.training.controls["lora"].trash.click()

    values = form.get_values()
    assert values["lora"] == "look_two.safetensors"
    assert values["positive_prompt"] == "zznew, scene one"
    assert form._widgets["lora"].findData("look_one.safetensors") < 0


def test_another_tab_holding_a_trashed_version_warns_and_its_click_switches_it(
        blank_panel, look_in_two_versions):
    blank_panel._workflow_dropdown.setCurrentIndex(_dropdown_index(blank_panel, "krea2_t2i"))
    form = blank_panel._param_form
    form.set_values({"lora": "look_one.safetensors", "positive_prompt": "zzold, scene one"})

    look_in_two_versions.unlink()
    blank_panel.lora_offers.stop_offering("look_one.safetensors")

    mark = form._warning_marks["lora"]
    assert mark.toolTip() == ("Not installed anymore, so nothing can be made with it. "
                              "Click to use Example Look 1.1 and its trigger word, zznew.")
    mark.pressed.emit()
    assert form.get_values()["lora"] == "look_two.safetensors"
    assert form.get_values()["positive_prompt"] == "zznew, scene one"


def test_a_tab_with_no_form_has_nothing_to_stop_offering(qtbot, tmp_path):
    tab = GenerateTab(ComfyUIClient(folders=SUITE_FOLDERS), Database(tmp_path / "t.db"))
    qtbot.addWidget(tab)
    tab._clear_form()

    tab.lora_offers.stop_offering("look_one.safetensors")

    assert tab.lora_value("lora") is None


def _turn_runs(tab):
    asked_for = []
    tab.turn_generate_requested.connect(
        lambda workflow, params, asked: asked_for.append((workflow, params, asked)))
    return asked_for


def test_generate_under_a_turn_asked_now_runs_that_turns_prompts_asked_of_the_image_shown(
        saved_panel, qtbot, monkeypatch):
    _rewriting(monkeypatch, answer=[("two women on a couch", "blurry"),
                                    ("two women on a bed", "blurry")])
    tab, db = saved_panel
    image = _image_row(db, "img1", prompt="a woman on a couch")
    tab.show_saved_generation(image, [image])
    exchange = _ask(tab, qtbot, "two women")
    qtbot.waitUntil(lambda: len(exchange.turns()) == 1 and bool(exchange.turns()[0][1]), timeout=5000)
    _ask(tab, qtbot, "on a bed")
    qtbot.waitUntil(lambda: _positive(tab) == "two women on a bed", timeout=5000)
    asked_for = _turn_runs(tab)

    exchange.generate_asked.emit(0)

    ((workflow, params, asked),) = asked_for
    assert workflow == image["workflow_name"]
    assert params["positive_prompt"] == "two women on a couch"
    assert asked["source_prompt_id"] == "img1"
    assert [turn.said for turn in asked["turns"]] == ["two women"]
    assert _positive(tab) == "two women on a bed"


def test_once_a_turn_made_an_item_the_turns_after_it_are_asked_of_that_item(
        saved_panel, qtbot, monkeypatch):
    _rewriting(monkeypatch, answer=[("two women on a couch", "blurry"),
                                    ("two women on a bed", "blurry")])
    tab, db = saved_panel
    image = _image_row(db, "img1", prompt="a woman on a couch")
    tab.show_saved_generation(image, [image])
    exchange = _ask(tab, qtbot, "two women")
    qtbot.waitUntil(lambda: len(exchange.turns()) == 1 and bool(exchange.turns()[0][1]), timeout=5000)
    _turn_runs(tab)
    exchange.generate_asked.emit(0)

    tab.note_turn_made("made-1")
    _ask(tab, qtbot, "on a bed")
    qtbot.waitUntil(lambda: _positive(tab) == "two women on a bed", timeout=5000)

    assert [entry.made for entry in exchange._entries()] == ["made-1", ""]
    asked = tab.asked()
    assert asked["source_prompt_id"] == "made-1"
    assert [turn.said for turn in asked["turns"]] == ["on a bed"]


def test_generate_under_a_turn_from_an_earlier_exchange_runs_its_item_with_its_prompts(
        saved_panel):
    tab, db = saved_panel
    _image_row(db, "src", prompt="a cat, a hat")
    image = _image_row(db, "img1", prompt="a cat, a scarf", steps=33)
    db.record_request(NewRequest(prompt_id="img1", source_prompt_id="src", heard="", asked="scarf"))
    db.requests.record_turns("img1", [Turn("no hat", "Took it off.", "a cat, a hat", "", "a cat", ""),
                                      Turn("scarf", "Gave a scarf.", "a cat", "", "a cat, a scarf", "")])
    tab.show_saved_generation(image, [image])
    asked_for = _turn_runs(tab)

    tab._param_form.request_exchange().generate_asked.emit(0)
    tab.note_turn_made("made-1")

    ((_workflow, params, asked),) = asked_for
    assert (params["positive_prompt"], params["steps"]) == ("a cat", 33)
    assert asked["source_prompt_id"] == "src"
    assert [turn.said for turn in asked["turns"]] == ["no hat"]
    assert [turn.made for turn in db.requests.exchange_of("img1")] == ["made-1", "img1"]


def test_generate_under_a_later_turn_of_an_earlier_exchange_marks_that_turn(saved_panel):
    tab, db = saved_panel
    image = _image_row(db, "img1", prompt="a cat, a scarf, red")
    db.record_request(NewRequest(prompt_id="img1", source_prompt_id="src", heard="", asked="red"))
    db.requests.record_turns("img1", [Turn(said, "Done.", "a", "", f"a {said}", "")
                                      for said in ("one", "two", "three", "red")])
    db.requests.mark_made("img1", 1, "made-1")
    tab.show_saved_generation(image, [image])
    asked_for = _turn_runs(tab)

    tab._param_form.request_exchange().generate_asked.emit(2)
    tab.note_turn_made("made-2")

    ((_workflow, params, asked),) = asked_for
    assert params["positive_prompt"] == "a three"
    assert asked["source_prompt_id"] == "made-1"
    assert [turn.made for turn in db.requests.exchange_of("img1")] == [
        "", "made-1", "made-2", "img1"]


_LOST = "This video's settings were lost, so it can't be made again"


def test_generate_is_gray_beside_an_item_whose_settings_were_lost_and_says_why(saved_panel):
    tab, db = saved_panel
    db.insert_generation(NewGeneration(
        prompt_id="lost1", workflow_name="sdxl_t2i", workflow_version="v004",
        params_json=json.dumps({"checkpoint": "made_up.safetensors"}), workflow_json="{}"))
    db.update_generation("lost1", status="completed",
                         output_files=json.dumps([{"filename": "lost1.png", "subfolder": "image"}]))
    db.say_why_it_cannot_be_made_again("lost1", _LOST)
    tab.show_saved_generation(db.get_generation("lost1"), [])

    tab._apply_generate_caption()

    assert not tab._generate_pair.isEnabled()
    assert tab._generate_btn.toolTip() == _LOST


def test_a_videos_file_and_created_are_listed_under_enhancements_never_metadata(saved_panel):
    tab, db = saved_panel
    video = _video_row(db, input_image="sdxl_img1.png")

    tab.show_saved_generation(video, [_image_row(db)])

    (original,) = _version_rows(tab)
    assert (original._title.text(), "video/vid1.mp4" in _row_texts(original)) == ("Original", True)
    assert {"File", "Created"}.isdisjoint(_shown_metadata(tab))


def test_a_prefill_on_the_same_workflow_shows_the_newest_result(
        qtbot, tmp_path, monkeypatch):
    db = Database(tmp_path / "t.db")
    db.insert_generation(NewGeneration(
        prompt_id="g1", workflow_name="sdxl_t2i", workflow_version=_SDXL_VERSION,
        positive_prompt="a wizard", params_json=json.dumps(_wiz_params()), workflow_json="{}",
    ))
    monkeypatch.setattr(generate_tab_module, "resolve_preview", lambda row, out: ("wiz.png", "image"))
    tab = GenerateTab(ComfyUIClient(folders=SUITE_FOLDERS), db)
    qtbot.addWidget(tab)
    tab.prefill("sdxl_t2i", {**_wiz_params(), "positive_prompt": "settings no folder holds"})
    shown = []
    monkeypatch.setattr(tab._viewport, "show_media",
                        lambda path, mt, generation: shown.append((path, mt, generation)))

    tab.prefill("sdxl_t2i", _wiz_params())

    assert shown[-1:] == [("wiz.png", "image", "g1")], (
        "the workflow did not change, so showing the folder's newest result cannot ride on the "
        "workflow dropdown's own signal")


def test_a_prefill_ends_the_tabs_watch_of_a_run(tab):
    tab.watch_folder("k", b"frame")

    tab.prefill("sdxl_t2i", _wiz_params())

    assert tab.watched_key() is None, (
        "the next frame of the run would land over the item these settings just put up")


def test_a_finished_run_with_no_file_leaves_the_frames_standing(tab, monkeypatch):
    monkeypatch.setattr(generate_tab_module, "resolve_preview", lambda row, out: None)
    tab._viewport.show_media = MagicMock()
    tab._viewport.show_message = MagicMock()
    tab._viewport.clear = MagicMock()

    tab.show_finished_media({"prompt_id": "g1"})

    tab._viewport.show_media.assert_not_called()
    assert tab._viewport.show_message.call_count + tab._viewport.clear.call_count == 0, (
        "with nothing to look at, the last frames stay rather than the pane going blank")


def test_the_drive_target_looks_the_video_up_at_each_ask(saved_panel, monkeypatch, tmp_path):
    tab, db = saved_panel
    video = _video_row(db, "vid1", input_image="hand.png")
    vpath = tmp_path / "vid1.mp4"
    vpath.write_bytes(b"v")
    _script_for(vpath)
    monkeypatch.setattr(generate_tab_module, "resolve_preview", lambda row, out: (vpath, "video"))
    tab.show_saved_generation(video, [])
    assert tab.osr2_drive_target() is not None

    monkeypatch.setattr(generate_tab_module, "resolve_preview", lambda row, out: None)

    assert tab.osr2_drive_target() is None, (
        "the file is looked for afresh at each ask, so one deleted since it was shown is caught")

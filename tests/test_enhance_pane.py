from __future__ import annotations

import json
import os
from datetime import datetime

import pytest
from PIL import Image
from PyQt6.QtCore import QEvent, QMimeData, QPoint, QPointF, QRect, QSize, Qt
from PyQt6.QtGui import (
    QDragEnterEvent,
    QDragLeaveEvent,
    QDragMoveEvent,
    QDropEvent,
    QEnterEvent,
    QFocusEvent,
    QPixmap,
)
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import (
    QApplication,
    QDialogButtonBox,
    QLabel,
    QLineEdit,
    QMenu,
    QPushButton,
    QScrollArea,
    QToolButton,
    QVBoxLayout,
    QWidget,
)
from shared_ui.colors import BG_PRIMARY, BLUE, BORDER_SUBTLE, TEXT_MUTED, TEXT_PRIMARY, YELLOW
from shared_ui.icons import CANVAS
from shared_ui.spacing import BUTTON_SIZE_HUD
from shared_ui.toggle_switch import ToggleSwitch

import origenerator.gui.enhance_pane as enhance_pane_module
import origenerator.gui.training_controls as training_controls_module
import origenerator.workflows.detail_parts as parts
from origenerator import config, fix_training
from origenerator.box_breaks import BOX_BREAK
from origenerator.enhance_presets import Preset
from origenerator.gallery import (
    MATCH_SOURCE_MODEL,
    EnhanceSettings,
    EnhanceVersion,
    SettingsGroup,
    default_enhance_params,
    full_settings,
)
from origenerator.gui import drag_thumbnail, icons
from origenerator.gui.collapsible_section import CollapsibleSection
from origenerator.gui.drag_thumbnail import THUMBNAIL_MAX
from origenerator.gui.drags import under_way
from origenerator.gui.drop_style import AIMED, LIT
from origenerator.gui.enhance_pane import EnhancePane
from origenerator.gui.enhance_versions import (
    Dating,
    EnhanceOffer,
    EnhanceVersions,
    RunningEnhancement,
    _AddRow,
    _PendingRow,
    _VersionRow,
    enhance_version_mime,
    params_from_mime,
)
from origenerator.gui.prompt_marks import RESOLVE_IN_BOTH_PROMPTS, problem_to_resolve
from origenerator.gui.stylesheet import build_stylesheet
from origenerator.model_titles import model_title
from origenerator.workflows import WORKFLOW_REGISTRY
from origenerator.workflows.detail_parts import DEFAULT_FIX_DENOISE, part_table
from origenerator.workflows.model_files import NO_LORA
from tests import gestures
from tests.drop_style_seen import worn
from tests.text_readers import clip_reader

_FOUND_DETECTORS = ("face_finder.pt", "hand_finder.pt")


def _panel(qtbot, detectors=_FOUND_DETECTORS, **seams):
    edits = []
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(parts, "list_detector_files", lambda: list(detectors))
        mp.setattr(parts, "list_outline_detector_files", list)
        pane = EnhancePane(edits.append, **seams)
    qtbot.addWidget(pane)
    return pane, edits


def test_the_pane_reads_the_enhancers_setting_definitions_once(qtbot, monkeypatch):
    enhancer = WORKFLOW_REGISTRY["image_enhance"]
    read, definitions = [], enhancer.param_definitions
    monkeypatch.setattr(enhancer, "param_definitions",
                        lambda: read.append("read") or definitions())

    _panel(qtbot)

    assert read == ["read"], (
        "reading the definitions scans the model folders, and every field of the pane would "
        "otherwise pay for that scan again")


def _versions(count, params=None):
    if not count:
        return []
    return [
        EnhanceVersion(i, f"Enhancement {i}/{count}", {"filename": f"e{i}.png", "subfolder": "image"},
                     dict(params or {}))
        for i in range(count, 0, -1)
    ] + [EnhanceVersion(0, "Original", {"filename": "src.png", "subfolder": "image"})]


def _items(versions):
    return [(version, None) for version in versions]



def test_a_fresh_panel_reads_as_the_workflow_defaults_tick_off(qtbot):
    pane, _ = _panel(qtbot)
    settings = pane.settings()
    assert settings.auto is False
    assert settings.params["enhance_scale"] == default_enhance_params()["enhance_scale"]
    assert settings.params["checkpoint"] == MATCH_SOURCE_MODEL


def test_the_model_left_to_match_the_source_says_which_model_it_falls_back_to(qtbot):
    pane, _ = _panel(qtbot)
    fallback = model_title(WORKFLOW_REGISTRY["image_enhance"].default_params()["checkpoint"])

    assert pane._model.itemText(0) == (
        f"(match the source image's model, or fall back to default model {fallback})")
    assert pane._model.itemData(0) == MATCH_SOURCE_MODEL


def test_auto_enhance_is_a_bare_switch_at_the_top_right(qtbot):
    pane, _ = _panel(qtbot)
    assert isinstance(pane._auto, ToggleSwitch), (
        "auto-enhance is the pane's power, not one of its settings, so it is a bare switch on the "
        "title row and no labeled checkbox among them")
    assert pane._auto.isCheckable()
    assert pane._auto.text() == ""
    assert pane._auto.toolTip()

    title_row = pane.layout().itemAt(0).layout()
    assert title_row.itemAt(0).widget().text() == "Enhance"
    assert title_row.itemAt(title_row.count() - 1).widget() is pane._auto
    assert title_row.itemAt(1).spacerItem() is not None


def test_the_switch_flips_and_reports(qtbot):
    switch = ToggleSwitch("Auto-enhance new images")
    qtbot.addWidget(switch)
    flips = []
    switch.toggled.connect(flips.append)

    switch.setChecked(True)
    assert flips == [True]
    switch.click()
    assert flips == [True, False]


def test_the_switch_draws_at_both_states(qtbot):
    switch = ToggleSwitch("Auto")
    qtbot.addWidget(switch)
    switch.resize(switch.sizeHint())
    off = switch.grab().toImage()
    switch.setChecked(True)
    on = switch.grab().toImage()
    assert not off.isNull()
    assert not on.isNull()
    assert off != on


def test_loading_a_folders_settings_writes_nothing_back(qtbot):
    pane, edits = _panel(qtbot)
    pane.show_settings(EnhanceSettings(auto=True, params={"enhance_steps": 40}))
    assert edits == [], (
        "opening a folder fills the pane and is no edit: saved back, it would stamp defaults over "
        "settings it failed to load")
    assert pane.settings().auto is True
    assert pane.settings().params["enhance_steps"] == 40


def test_every_setting_reports_its_edit(qtbot):
    pane, edits = _panel(qtbot)
    pane._auto.setChecked(True)
    pane._scale.setValue(3.0)
    pane._steps.setValue(35)
    pane._denoise.setValue(0.4)

    assert len(edits) == 4
    latest = edits[-1]
    assert latest.auto is True
    assert latest.params["enhance_scale"] == 3.0
    assert latest.params["enhance_steps"] == 35
    assert latest.params["enhance_denoise"] == 0.4


def test_every_fixable_part_gets_a_tick_and_a_number_of_its_own(qtbot):
    pane, edits = _panel(qtbot)
    assert list(pane._fixes) == [part.name for part in part_table()]
    assert pane.settings().params["enhance_detail_fixes"] == {}
    assert pane._fixes["faces"].value() == DEFAULT_FIX_DENOISE

    pane._fix_checks["faces"].setChecked(True)
    pane._fix_checks["hands"].setChecked(True)
    pane._fixes["hands"].setValue(0.6)

    assert edits[-1].params["enhance_detail_fixes"] == {
        "faces": DEFAULT_FIX_DENOISE, "hands": 0.6}, (
        "each part's denoise is its own, apart from the enhancement's and from the other "
        "parts', because it can afford to be far bolder: nothing outside the regions a detector "
        "finds is touched, and a mouth wants a harder redraw than a face does")
    assert pane._fixes["faces"].toolTip()
    assert pane._fix_checks["faces"].toolTip()


def test_a_press_on_the_all_checkbox_turns_on_every_fix_that_can_run_and_tells_once(qtbot):
    pane, edits = _panel(qtbot)

    pane._all_fixes_check.click()

    assert len(edits) == 1
    assert sorted(edits[-1].params["enhance_detail_fixes"]) == ["faces", "hands"]
    assert pane._fixes["faces"].isEnabled()


def _type_into(field, text):
    field.lineEdit().selectAll()
    QTest.keyClicks(field.lineEdit(), text)


def _all_number_is_gray(pane):
    return TEXT_MUTED.name() in pane._all_fixes_number.styleSheet()


def test_a_second_press_on_the_all_checkbox_turns_every_fix_off(qtbot):
    pane, edits = _panel(qtbot)
    pane._all_fixes_check.click()

    pane._all_fixes_check.click()

    assert edits[-1].params["enhance_detail_fixes"] == {}
    assert not pane._fixes["faces"].isEnabled()


def test_the_all_checkbox_shows_how_many_of_the_fixes_that_can_run_are_on(qtbot):
    pane, _ = _panel(qtbot)
    assert pane._all_fixes_check.checkState() == Qt.CheckState.Unchecked

    pane._fix_checks["faces"].setChecked(True)
    assert pane._all_fixes_check.checkState() == Qt.CheckState.PartiallyChecked

    pane._fix_checks["hands"].setChecked(True)
    assert pane._all_fixes_check.checkState() == Qt.CheckState.Checked

    pane._fix_checks["hands"].setChecked(False)
    assert pane._all_fixes_check.checkState() == Qt.CheckState.PartiallyChecked

    pane._fix_checks["faces"].setChecked(False)
    assert pane._all_fixes_check.checkState() == Qt.CheckState.Unchecked


def test_a_press_on_the_half_checked_all_checkbox_turns_the_rest_on(qtbot):
    pane, edits = _panel(qtbot)
    pane._fix_checks["faces"].setChecked(True)

    pane._all_fixes_check.click()

    assert sorted(edits[-1].params["enhance_detail_fixes"]) == ["faces", "hands"]
    assert pane._all_fixes_check.checkState() == Qt.CheckState.Checked


def test_settings_shown_in_the_pane_show_on_the_all_checkbox_and_the_all_number(qtbot):
    pane, _ = _panel(qtbot)

    pane.show_settings(EnhanceSettings(auto=False, params=full_settings(
        {"enhance_detail_fixes": {"faces": 0.6, "hands": 0.6}})))

    assert pane._all_fixes_check.checkState() == Qt.CheckState.Checked
    assert pane._all_fixes_number.value() == 0.6
    assert _all_number_is_gray(pane)


def test_settings_shown_with_differing_fixes_leave_the_all_number_as_it_was_and_white(qtbot):
    pane, _ = _panel(qtbot)
    _type_into(pane._all_fixes_number, "0.7")

    pane.show_settings(EnhanceSettings(auto=False, params=full_settings(
        {"enhance_detail_fixes": {"faces": 0.6, "hands": 0.5}})))

    assert pane._all_fixes_number.value() == 0.7
    assert not _all_number_is_gray(pane)


def test_a_number_typed_into_all_sets_every_fix_that_can_run_on_or_off_and_tells_once(qtbot):
    pane, edits = _panel(qtbot)
    pane._fix_checks["faces"].setChecked(True)
    edits.clear()

    _type_into(pane._all_fixes_number, "0.7")
    QTest.keyClick(pane._all_fixes_number, Qt.Key.Key_Return)

    assert len(edits) == 1
    assert edits[-1].params["enhance_detail_fixes"] == {"faces": 0.7}
    assert pane._fixes["hands"].value() == 0.7


def test_a_fix_with_no_detector_is_left_out_of_all(qtbot):
    pane, edits = _panel(qtbot)
    before = pane._fixes["teeth"].value()

    pane._all_fixes_check.click()
    _type_into(pane._all_fixes_number, "0.7")

    assert "teeth" not in edits[-1].params["enhance_detail_fixes"]
    assert pane._fixes["teeth"].value() == before
    assert _all_number_is_gray(pane)


def test_the_all_number_is_gray_once_every_fix_has_it(qtbot):
    pane, _ = _panel(qtbot)
    assert _all_number_is_gray(pane)

    _type_into(pane._all_fixes_number, "0.7")

    assert _all_number_is_gray(pane)


def test_the_all_number_keeps_its_value_and_goes_white_while_a_fix_differs_from_it(qtbot):
    pane, _ = _panel(qtbot)
    _type_into(pane._all_fixes_number, "0.7")

    pane._fixes["hands"].setValue(0.5)
    assert pane._all_fixes_number.value() == 0.7
    assert not _all_number_is_gray(pane)

    pane._fixes["hands"].setValue(0.7)
    assert _all_number_is_gray(pane)


def test_enter_in_the_white_all_number_applies_it_to_every_fix_again(qtbot):
    pane, edits = _panel(qtbot)
    _type_into(pane._all_fixes_number, "0.7")
    pane._fixes["hands"].setValue(0.5)
    edits.clear()

    QTest.keyClick(pane._all_fixes_number, Qt.Key.Key_Return)

    assert len(edits) == 1
    assert pane._fixes["hands"].value() == 0.7
    assert _all_number_is_gray(pane)


def test_moving_on_from_the_white_all_number_without_typing_changes_no_fix(qtbot):
    pane, edits = _panel(qtbot)
    _type_into(pane._all_fixes_number, "0.7")
    pane._fixes["hands"].setValue(0.5)
    edits.clear()

    QApplication.sendEvent(pane._all_fixes_number, QFocusEvent(QEvent.Type.FocusIn))
    QApplication.sendEvent(pane._all_fixes_number, QFocusEvent(QEvent.Type.FocusOut))

    assert edits == []
    assert pane._fixes["hands"].value() == 0.5


def test_enter_in_the_gray_all_number_tells_nobody(qtbot):
    pane, edits = _panel(qtbot)

    QTest.keyClick(pane._all_fixes_number, Qt.Key.Key_Return)

    assert edits == []


def test_with_no_fix_able_to_run_all_is_grayed(qtbot):
    pane, _ = _panel(qtbot, detectors=())

    for one in (pane._all_fixes_check, pane._all_fixes_number,
                pane._label_for(pane._all_fixes_number)):
        assert not one.isEnabled()


def test_all_comes_first_in_the_row_of_fixes_labeled_all_with_no_pencil(qtbot):
    pane, _ = _panel(qtbot)
    flow = pane._fixes["faces"].parent().parent().layout()
    first = flow.itemAt(0).widget()

    assert first is pane._all_fixes_number.parent()
    assert [label.text() for label in first.findChildren(QLabel)] == ["All"]
    assert not first.findChildren(QToolButton)
    assert first.objectName() == pane._fixes["faces"].parent().objectName()
    assert pane._all_fixes_check.toolTip()
    assert pane._all_fixes_number.toolTip()
    assert pane._all_fixes_number.minimumWidth() == pane._fixes["faces"].minimumWidth()


def test_the_all_set_is_as_tall_as_a_fix_with_its_number_on_the_same_line(qtbot):
    pane, _ = _panel(qtbot)
    pane.setStyleSheet(build_stylesheet() + pane.styleSheet())
    _laid_out_at(pane, 2000)
    fix = pane._fixes["faces"]
    every = pane._all_fixes_number

    assert every.parent().height() == fix.parent().height()
    assert every.mapTo(pane, QPoint(0, 0)).y() == fix.mapTo(pane, QPoint(0, 0)).y()
    assert (pane._all_fixes_check.mapTo(pane, QPoint(0, 0)).y()
            == pane._fix_checks["faces"].mapTo(pane, QPoint(0, 0)).y())


def test_a_fix_field_is_only_as_wide_as_the_number_it_holds(qtbot):
    pane, _ = _panel(qtbot)
    spinner = pane._fixes["faces"]
    digits = spinner.fontMetrics().horizontalAdvance("0.00")

    assert digits < spinner.minimumWidth() <= digits + 30, (
        "each number is exactly as wide as its digits need, because the point of the line is "
        "reading all the parts at once, and one number stretched to fill the pane costs another "
        "part its place")
    assert spinner.minimumWidth() == spinner.maximumWidth()
    assert spinner.minimumWidth() < spinner.sizeHint().width()
    assert spinner.buttonSymbols() == spinner.ButtonSymbols.NoButtons, (
        "no step arrows: a pair for every part costs more width than the numbers beside them, "
        "and a denoise is typed or nudged with the arrow keys")


def test_the_fixes_line_wraps_rather_than_widening_the_panel(qtbot):
    pane, _ = _panel(qtbot)
    host = pane._fixes["faces"].parent().parent()
    flow = host.layout()
    pairs = [flow.itemAt(i).widget() for i in range(flow.count())]

    assert flow.heightForWidth(120) > flow.heightForWidth(4000), (
        "a pane too narrow for the line wraps the last parts onto a second line instead of "
        "cutting them off")
    assert host.hasHeightForWidth()
    assert host.minimumSizeHint().width() <= max(
        pair.sizeHint().width() for pair in pairs) + 8, (
        "the line never widens the window, which tiles into a third of a monitor")


def _laid_out_at(pane, width, height=900):
    pane.show()
    pane.resize(width, height)
    for _ in range(3):
        QApplication.processEvents()


def _numbers(pane):
    return (pane._scale, pane._steps, pane._denoise)


def test_the_numbers_share_a_line_while_they_fit_and_take_a_line_each_when_not(qtbot):
    pane, _ = _panel(qtbot)
    (fixes_heading,) = [label for label in pane.findChildren(QLabel)
                        if label.text() == "Fixes"]

    def top(widget):
        return widget.mapTo(pane, QPoint(0, 0)).y()

    _laid_out_at(pane, 2000)
    assert len({top(field) for field in _numbers(pane)}) == 1

    _laid_out_at(pane, pane.minimumSizeHint().width())
    rows = [top(field) for field in _numbers(pane)]
    assert rows == sorted(set(rows))
    assert len(rows) == 3
    assert top(fixes_heading) >= rows[-1] + pane._denoise.height()


def test_squeezed_shorter_than_its_settings_the_panel_scrolls_down_to_them(qtbot):
    pane, _ = _panel(qtbot)
    _laid_out_at(pane, 600, pane.minimumSizeHint().height())
    (scroll,) = pane.findChildren(QScrollArea)
    last_part = list(pane._fixes.values())[-1]

    assert scroll.verticalScrollBar().maximum() > 0
    scroll.ensureWidgetVisible(last_part)
    shown = QRect(last_part.mapTo(scroll.viewport(), QPoint(0, 0)), last_part.size())
    assert scroll.viewport().rect().contains(shown)


def test_squeezed_narrower_than_its_settings_the_panel_scrolls_sideways_to_them(qtbot):
    pane, _ = _panel(qtbot)
    (scroll,) = pane.findChildren(QScrollArea)
    _laid_out_at(pane, 2000)
    narrowest_settings = scroll.widget().minimumSizeHint().width()

    _laid_out_at(pane, narrowest_settings // 2)

    assert pane.width() < narrowest_settings
    assert scroll.horizontalScrollBar().maximum() > 0


def test_given_the_height_it_asks_for_the_panel_shows_its_settings_unscrolled(qtbot):
    pane, _ = _panel(qtbot)
    (scroll,) = pane.findChildren(QScrollArea)
    for width in (2000, 700, pane.minimumSizeHint().width()):
        _laid_out_at(pane, width)
        _laid_out_at(pane, width, pane.sizeHint().height())
        assert scroll.verticalScrollBar().maximum() == 0, width


def test_the_enhance_button_asks_for_an_enhance_from_outside_the_scroll(qtbot):
    pane, _ = _panel(qtbot)
    (button,) = [b for b in pane.findChildren(QPushButton) if b.text() == "Enhance"]
    (scroll,) = pane.findChildren(QScrollArea)
    asked = []
    pane.enhance_requested.connect(lambda: asked.append(True))

    qtbot.mouseClick(button, Qt.MouseButton.LeftButton)

    assert asked == [True]
    assert not scroll.isAncestorOf(button)


def test_the_enhance_button_is_yellow_with_dark_words_until_it_goes_dark(qtbot):
    pane, _ = _panel(qtbot)
    pane.show()
    QApplication.processEvents()
    (button,) = [b for b in pane.findChildren(QPushButton) if b.text() == "Enhance"]
    image = button.grab().toImage()

    assert _share_painted(image, YELLOW) > 0.5
    assert not any(min(image.pixelColor(x, y).getRgb()[:3]) > 200
                   for y in range(image.height()) for x in range(image.width()))

    pane.show_offer(False, "Nothing here to enhance")
    assert _share_painted(button.grab().toImage(), YELLOW) == 0


def test_the_enhance_button_says_what_it_would_do_and_goes_dark_with_nothing_to_do(qtbot):
    pane, _ = _panel(qtbot)
    (button,) = [b for b in pane.findChildren(QPushButton) if b.text() == "Enhance"]

    pane.show_offer(True, "Enhance 2 items")
    assert button.isEnabled()
    assert button.toolTip() == "Enhance 2 items"

    pane.show_offer(False, "Nothing here to enhance")
    assert not button.isEnabled()
    assert button.toolTip() == "Nothing here to enhance"


def test_the_presets_and_save_sit_left_of_the_enhance_button_on_its_line(qtbot):
    pane, _ = _panel(qtbot)
    line = (pane._preset_dropdown, pane._preset_button, pane._enhance_button)

    for width in (2000, pane.minimumSizeHint().width()):
        _laid_out_at(pane, width)
        lefts = [widget.mapTo(pane, QPoint(0, 0)).x() for widget in line]
        middles = {widget.mapTo(pane, QPoint(0, widget.height() // 2)).y() for widget in line}
        assert lefts == sorted(lefts), width
        assert len(middles) == 1, width


def _presets():
    return [Preset("Crisp", {**default_enhance_params(), "enhance_steps": 40}),
            Preset("Soft", {**default_enhance_params(), "enhance_steps": 30})]


def _listed(dropdown):
    return [dropdown.itemText(index) for index in range(dropdown.count())]


def test_the_dropdown_lists_the_presets_and_reads_custom_while_the_settings_are_none_of_them(
        qtbot):
    pane, _ = _panel(qtbot)

    pane.show_presets(_presets())

    assert _listed(pane._preset_dropdown) == ["Crisp", "Soft"]
    assert pane._preset_dropdown.currentIndex() == -1
    assert pane._preset_dropdown.placeholderText() == "(custom)"
    assert pane._preset_button.text() == "Save…"


def test_the_presets_and_their_button_say_what_each_does(qtbot):
    pane, _ = _panel(qtbot)
    pane.show_presets(_presets())
    assert pane._preset_dropdown.toolTip() == "Pick a preset to use its settings"
    assert pane._preset_button.toolTip() == "Save these settings as a preset"

    pane._steps.setValue(30)

    assert pane._preset_button.toolTip() == "Rename this preset"


def test_the_open_list_shows_each_preset_s_whole_name_however_narrow_the_box(qtbot):
    pane, _ = _panel(qtbot)
    long_name = "2x · 20 steps · 0.15 redraw · faces 0.45 & hands 0.6 · driftwood_v1.safetensors"

    pane.show_presets([Preset(long_name, default_enhance_params())])

    dropdown = pane._preset_dropdown
    assert dropdown.view().minimumWidth() > dropdown.fontMetrics().horizontalAdvance(long_name)


def test_the_dropdown_shows_the_preset_the_settings_are_and_the_button_offers_to_rename_it(
        qtbot):
    pane, _ = _panel(qtbot)
    pane.show_settings(EnhanceSettings(params={**default_enhance_params(), "enhance_steps": 30}))

    pane.show_presets(_presets())

    assert pane._preset_dropdown.currentText() == "Soft"
    assert pane._preset_button.text() == "Rename…"


def test_settings_turned_or_loaded_onto_a_preset_show_it_and_off_one_read_custom_again(qtbot):
    pane, _ = _panel(qtbot)
    pane.show_presets(_presets())

    pane._steps.setValue(30)
    assert pane._preset_dropdown.currentText() == "Soft"

    pane._steps.setValue(31)
    assert pane._preset_dropdown.currentIndex() == -1
    assert pane._preset_button.text() == "Save…"

    pane.show_settings(EnhanceSettings(params={**default_enhance_params(), "enhance_steps": 40}))
    assert pane._preset_dropdown.currentText() == "Crisp"


def _pick(dropdown, index):
    # Qt's own order for a choice from the open list: the box moves to it, then says it was picked.
    dropdown.setCurrentIndex(index)
    dropdown.activated.emit(index)


def test_picking_a_preset_puts_its_settings_on_the_panel_and_leaves_the_switch_alone(qtbot):
    pane, edits = _panel(qtbot)
    pane._auto.setChecked(True)
    pane.show_presets(_presets())

    _pick(pane._preset_dropdown, 1)

    assert pane._steps.value() == 30
    assert edits[-1].params["enhance_steps"] == 30
    assert edits[-1].auto is True
    assert pane._preset_dropdown.currentText() == "Soft"
    assert pane._preset_button.text() == "Rename…"


def _answering_the_name_box(monkeypatch, name, ok=True):
    asked = []

    def answer(parent, title, label, *args, **kwargs):
        asked.append((title, label, kwargs.get("text", "")))
        return name, ok

    monkeypatch.setattr(enhance_pane_module.QInputDialog, "getText", staticmethod(answer))
    return asked


def test_save_asks_for_a_name_and_saves_the_settings_on_the_panel_under_it(qtbot, monkeypatch):
    pane, _ = _panel(qtbot)
    pane.show_presets(_presets())
    asked = _answering_the_name_box(monkeypatch, "  Bright  ")
    saved = []
    pane.preset_saved.connect(saved.append)

    qtbot.mouseClick(pane._preset_button, Qt.MouseButton.LeftButton)

    assert asked == [("Save Preset", "Preset name:", "")]
    assert saved == ["Bright"]


def test_rename_asks_with_the_presets_own_name_and_renames_that_preset(qtbot, monkeypatch):
    pane, _ = _panel(qtbot)
    pane.show_settings(EnhanceSettings(params={**default_enhance_params(), "enhance_steps": 30}))
    pane.show_presets(_presets())
    asked = _answering_the_name_box(monkeypatch, "Gentle")
    renamed = []
    pane.preset_renamed.connect(lambda index, name: renamed.append((index, name)))

    qtbot.mouseClick(pane._preset_button, Qt.MouseButton.LeftButton)

    assert asked == [("Rename Preset", "Preset name:", "Soft")]
    assert renamed == [(1, "Gentle")]


@pytest.mark.parametrize(("name", "ok"), [("   ", True), ("Bright", False)])
def test_a_blank_name_or_a_cancel_names_nothing(qtbot, monkeypatch, name, ok):
    pane, _ = _panel(qtbot)
    pane.show_presets(_presets())
    _answering_the_name_box(monkeypatch, name, ok)
    named = []
    pane.preset_saved.connect(named.append)

    qtbot.mouseClick(pane._preset_button, Qt.MouseButton.LeftButton)

    assert named == []


def test_the_fields_line_up_down_the_panel_either_way_the_numbers_lie(qtbot):
    pane, _ = _panel(qtbot)

    def left(widget):
        return widget.mapTo(pane, QPoint(0, 0)).x()

    for width in (2000, pane.minimumSizeHint().width()):
        _laid_out_at(pane, width)
        assert left(pane._model) == left(pane._upscaler) == left(pane._scale), width
    assert len({left(field) for field in _numbers(pane)}) == 1


def test_a_number_is_never_squeezed_narrower_than_its_widest_value(qtbot):
    pane, _ = _panel(qtbot)
    pane.setStyleSheet(build_stylesheet() + pane.styleSheet())
    for width in range(pane.minimumSizeHint().width(), 1201, 20):
        _laid_out_at(pane, width)
        for field in _numbers(pane):
            widest = max(field.textFromValue(field.minimum()),
                         field.textFromValue(field.maximum()), key=len)
            digits = field.fontMetrics().horizontalAdvance(widest)
            frame_and_buttons = field.width() - field.lineEdit().width()
            assert field.width() >= field.minimumWidth() >= digits + frame_and_buttons, width


def test_unticking_a_part_drops_its_fix_but_keeps_its_number(qtbot):
    pane, edits = _panel(qtbot)
    pane._fix_checks["faces"].setChecked(True)
    pane._fixes["faces"].setValue(0.7)

    pane._fix_checks["faces"].setChecked(False)

    assert edits[-1].params["enhance_detail_fixes"] == {}, (
        "only the ticked parts go into the settings: an unticked part is one this enhancement "
        "does not do, and leaving it out lets equal settings compare equal")
    assert pane._fixes["faces"].value() == 0.7
    assert not pane._fixes["faces"].isEnabled()


def test_an_unticked_parts_name_and_number_gray_out(qtbot):
    pane, _ = _panel(qtbot)
    label = pane._label_for(pane._fixes["faces"])

    assert not label.isEnabled()
    assert not pane._fixes["faces"].isEnabled()

    pane._fix_checks["faces"].setChecked(True)

    assert label.isEnabled()
    assert pane._fixes["faces"].isEnabled()


def test_a_part_with_no_detector_installed_cannot_be_ticked(qtbot):
    pane, _ = _panel(qtbot, detectors=("face_finder.pt",))
    assert pane._fix_checks["faces"].isEnabled()
    assert not pane._fix_checks["hands"].isEnabled()
    tooltip = pane._fix_checks["hands"].toolTip()
    assert "models/ultralytics/bbox" in tooltip
    assert "models/ultralytics/segm" in pane._fix_checks["skin"].toolTip()
    assert "Impact Subpack" in tooltip
    assert "hand" in tooltip
    assert pane._label_for(pane._fixes["hands"]).toolTip() == tooltip


def test_a_detector_by_another_name_does_not_count_as_installed(qtbot):
    pane, _ = _panel(qtbot, detectors=("cat_finder.pt",))
    assert not any(checkbox.isEnabled() for checkbox in pane._fix_checks.values()), (
        "some other detector in that folder would leave every part tickable and every pass finding nothing")


def _mean_ink(widget) -> float:
    """Mean brightness over the app's background, rendered onto a filled pixmap since a bare Qt ``grab`` leaves unpainted pixels uninitialized."""
    pixmap = QPixmap(widget.size())
    pixmap.fill(BG_PRIMARY)
    widget.render(pixmap, QPoint(), flags=QWidget.RenderFlag.DrawChildren)
    image = pixmap.toImage()
    total = 0
    for y in range(image.height()):
        for x in range(image.width()):
            color = image.pixelColor(x, y)
            total += color.red() + color.green() + color.blue()
    return total / max(1, image.width() * image.height() * 3)


def test_switched_off_the_panel_actually_looks_switched_off(qtbot):
    pane, _ = _panel(qtbot)
    pane.show_settings(EnhanceSettings(auto=True, params={}))
    pane.resize(360, 150)
    with qtbot.waitExposed(pane):
        pane.show()
    live = _mean_ink(pane)

    pane.set_applicable(False, "no video enhancer")

    assert not pane.isEnabled()
    assert pane.toolTip() == "no video enhancer"
    assert _mean_ink(pane) < live, (
        "the app's stylesheet colors every label, dropdown and spinner outright and names no disabled "
        "state, so a pane only disabled went on reading as live")

    pane.set_applicable(True)
    assert pane.isEnabled()
    assert pane.toolTip() == ""


def test_coming_back_on_leaves_the_detail_pass_dimmed_without_a_detector(qtbot):
    pane, _ = _panel(qtbot, detectors=())
    pane.set_applicable(False, "nope")
    pane.set_applicable(True)
    assert pane.isEnabled()
    assert not pane._fix_checks["faces"].isEnabled()


def test_a_model_no_longer_installed_is_still_shown(qtbot):
    pane, _ = _panel(qtbot)
    pane.show_settings(EnhanceSettings(params={"checkpoint": "retired_v1.safetensors"}))
    assert pane.settings().params["checkpoint"] == "retired_v1.safetensors", (
        "a folder set against a checkpoint since removed comes back reading as that checkpoint, "
        "never snapped to whatever sorts first")


def test_the_model_dropdown_shows_a_files_title_and_keeps_its_name(qtbot, titled_models):
    titled_models({"example_model": "Example Model v2"})
    pane, _ = _panel(qtbot)

    pane.show_settings(EnhanceSettings(params={"checkpoint": "example_model.safetensors"}))

    assert pane._model.currentText() == "Example Model v2"
    assert pane.settings().params["checkpoint"] == "example_model.safetensors"


def test_settings_survive_a_load_and_read_back(qtbot):
    pane, _ = _panel(qtbot)
    original = EnhanceSettings(auto=True, params=dict(default_enhance_params(),
                                                      enhance_scale=2.5,
                                                      enhance_steps=31,
                                                      enhance_denoise=0.22))
    pane.show_settings(original)
    assert pane.settings() == original



def _rows(widget):
    return widget._host.findChildren(_VersionRow)


def _labels(widget):
    return [row._title.text() for row in _rows(widget)]


def _facts(row):
    return " / ".join(lbl.text().replace("\u200b", "")
                      for lbl in row.findChildren(QLabel)
                      if lbl.text() and lbl.text() != "—")


def test_an_unenhanced_image_shows_no_version_strip(qtbot):
    versions = EnhanceVersions()
    qtbot.addWidget(versions)
    versions.show_versions(_items(_versions(0)))
    assert versions.isHidden()


def test_a_lone_enhancement_is_still_worth_showing(qtbot):
    versions = EnhanceVersions()
    qtbot.addWidget(versions)
    versions.show_versions(_items([
        EnhanceVersion(1, "Enhancement 1/1", {"filename": "img.png"},
                     {"enhance_scale": 2.0, "enhance_steps": 20}),
    ]))
    assert not versions.isHidden()
    assert len(_rows(versions)) == 1


def test_versions_are_shown_newest_first(qtbot):
    versions = EnhanceVersions()
    qtbot.addWidget(versions)
    versions.show_versions(_items(_versions(2)))
    assert not versions.isHidden()
    assert _labels(versions) == ["Enhancement 2/2", "Enhancement 1/2", "Original"]


def test_clicking_a_version_reports_its_position(qtbot):
    versions = EnhanceVersions()
    qtbot.addWidget(versions)
    versions.show_versions(_items(_versions(2)))
    picked = []
    versions.version_selected.connect(picked.append)

    row = _rows(versions)[2]
    qtbot.mousePress(row, Qt.MouseButton.LeftButton)
    qtbot.mouseRelease(row, Qt.MouseButton.LeftButton)

    assert picked == [2]
    assert versions.selected_positions() == [2]


def test_each_version_carries_its_own_file_and_created_rows(qtbot):
    versions = EnhanceVersions()
    qtbot.addWidget(versions)
    versions.show_versions(_items(_versions(1, {"enhance_scale": 2.0})),
                         dating=Dating("2026-08-01"))

    facts = _facts(_rows(versions)[0])
    assert "Enhancement" in facts
    assert "2x" in facts
    assert "File" in facts
    assert "image/e1.png" in facts
    assert "Created" in facts
    assert "2026-08-01" in facts


def test_a_file_row_can_be_copied_and_revealed(qtbot):
    versions = EnhanceVersions()
    qtbot.addWidget(versions)
    versions.show_versions(_items(_versions(1)))

    names = {b.objectName() for b in _rows(versions)[0].findChildren(QPushButton)}
    assert "copyButton" in names
    assert "revealButton" in names


def test_a_versions_settings_caption_its_row(qtbot):
    versions = EnhanceVersions()
    qtbot.addWidget(versions)
    versions.show_versions(_items(_versions(1, {"enhance_scale": 2.0, "enhance_steps": 20})))
    facts = _facts(_rows(versions)[0])
    assert "2x" in facts
    assert "20 steps" in facts


def test_rebuilding_for_another_image_drops_the_old_rows(qtbot):
    versions = EnhanceVersions()
    qtbot.addWidget(versions)
    versions.show_versions(_items(_versions(2)))
    versions.show_versions(_items(_versions(1)))
    assert _labels(versions) == ["Enhancement 1/1", "Original"]



def _click(qtbot, row, modifier=Qt.KeyboardModifier.NoModifier):
    qtbot.mousePress(row, Qt.MouseButton.LeftButton, modifier)
    qtbot.mouseRelease(row, Qt.MouseButton.LeftButton, modifier)


def test_clicking_anywhere_on_a_row_picks_it(qtbot):
    versions = EnhanceVersions()
    qtbot.addWidget(versions)
    versions.show_versions(_items(_versions(1)), dating=Dating("2026-08-01"))
    row = _rows(versions)[0]

    targets = [row._thumbnail, row._title]
    targets += [lbl for lbl in row.findChildren(QLabel) if lbl.text() == "File"]
    for target in targets:
        assert row.childAt(target.mapTo(row, QPoint(3, 3))) is None, target.text()


def test_the_buttons_on_a_row_still_take_their_own_clicks(qtbot):
    versions = EnhanceVersions()
    qtbot.addWidget(versions)
    versions.show_versions(_items(_versions(1)))
    row = _rows(versions)[0]

    buttons = row.findChildren(QPushButton)
    assert {b.objectName() for b in buttons} == {"copyButton", "deleteButton",
                                                 "revealButton"}
    for button in buttons:
        assert row.childAt(button.mapTo(row, QPoint(3, 3))) is button


def test_a_rows_text_offers_no_copy_or_select_all_menu(qtbot):
    versions = EnhanceVersions()
    qtbot.addWidget(versions)
    versions.show_versions(_items(_versions(1)), dating=Dating("2026-08-01"))
    row = _rows(versions)[0]

    for label in row.findChildren(QLabel):
        assert label.contextMenuPolicy() == Qt.ContextMenuPolicy.NoContextMenu
    assert row.contextMenuPolicy() == Qt.ContextMenuPolicy.CustomContextMenu


def test_a_plain_click_picks_one_version_at_a_time(qtbot):
    versions = EnhanceVersions()
    qtbot.addWidget(versions)
    versions.show_versions(_items(_versions(2)))

    _click(qtbot, _rows(versions)[0])
    _click(qtbot, _rows(versions)[2])

    assert versions.selected_positions() == [2]


def test_ctrl_click_adds_to_the_picking(qtbot):
    versions = EnhanceVersions()
    qtbot.addWidget(versions)
    versions.show_versions(_items(_versions(2)))
    shown = []
    versions.version_selected.connect(shown.append)

    _click(qtbot, _rows(versions)[0])
    _click(qtbot, _rows(versions)[1], Qt.KeyboardModifier.ControlModifier)

    assert versions.selected_positions() == [0, 1]
    assert shown == [0], (
        "Ctrl and Shift leave the preview where it was: the gesture is these ones, aimed at the "
        "Delete that follows, and swapping the preview under each click would fight it")


@pytest.mark.parametrize(("clicked", "shift_clicked", "run"),
                         [(0, 2, [0, 1, 2]), (3, 1, [1, 2, 3])], ids=["down", "up"])
def test_shift_click_picks_the_run_from_the_version_last_clicked(qtbot, clicked,
                                                               shift_clicked, run):
    versions = EnhanceVersions()
    qtbot.addWidget(versions)
    versions.show_versions(_items(_versions(3)))
    shown = []
    versions.version_selected.connect(shown.append)

    _click(qtbot, _rows(versions)[clicked])
    _click(qtbot, _rows(versions)[shift_clicked], Qt.KeyboardModifier.ShiftModifier)

    assert versions.selected_positions() == run
    assert shown == [clicked], (
        "Ctrl and Shift leave the preview where it was: the gesture is these ones, aimed at the "
        "Delete that follows, and swapping the preview under each click would fight it")


def test_an_arrow_after_a_shift_click_steps_on_from_the_version_shift_clicked(qtbot):
    versions = EnhanceVersions()
    qtbot.addWidget(versions)
    versions.show_versions(_items(_versions(3)))
    shown = []
    versions.version_selected.connect(shown.append)

    _click(qtbot, _rows(versions)[0])
    _click(qtbot, _rows(versions)[2], Qt.KeyboardModifier.ShiftModifier)
    qtbot.keyClick(_rows(versions)[2], Qt.Key.Key_Down)

    assert versions.selected_positions() == [3]
    assert shown == [0, 3]


def _clicked_into(qtbot, position, count=2):
    versions = EnhanceVersions()
    qtbot.addWidget(versions)
    versions.show_versions(_items(_versions(count)))
    shown = []
    versions.version_selected.connect(shown.append)
    row = _rows(versions)[position]
    _click(qtbot, row)
    return versions, row, shown


def test_a_shift_click_picks_the_run_from_the_version_the_arrows_reached(qtbot):
    versions, row, _shown = _clicked_into(qtbot, 0, count=3)

    qtbot.keyClick(row, Qt.Key.Key_Down)
    _click(qtbot, _rows(versions)[3], Qt.KeyboardModifier.ShiftModifier)

    assert versions.selected_positions() == [1, 2, 3]


def test_down_and_right_pick_and_show_the_version_under_the_one_clicked(qtbot):
    versions, row, shown = _clicked_into(qtbot, 0)

    qtbot.keyClick(row, Qt.Key.Key_Down)
    qtbot.keyClick(row, Qt.Key.Key_Right)

    assert shown == [0, 1, 2]
    assert versions.selected_positions() == [2]


def test_up_and_left_pick_and_show_the_version_over_the_one_clicked(qtbot):
    versions, row, shown = _clicked_into(qtbot, 2)

    qtbot.keyClick(row, Qt.Key.Key_Up)
    qtbot.keyClick(row, Qt.Key.Key_Left)

    assert shown == [2, 1, 0]
    assert versions.selected_positions() == [0]


@pytest.mark.parametrize(("clicked", "arrow"), [(0, Qt.Key.Key_Up), (2, Qt.Key.Key_Down)],
                         ids=["the top", "the foot"])
def test_an_arrow_off_either_end_of_the_list_stays_where_it_is(qtbot, clicked, arrow):
    versions, row, shown = _clicked_into(qtbot, clicked)

    qtbot.keyClick(row, arrow)

    assert shown == [clicked]
    assert versions.selected_positions() == [clicked]


def _clicked_under_the_enhance_row(qtbot, duplicate_of=None):
    versions = EnhanceVersions()
    qtbot.addWidget(versions)
    versions.show_versions(_items(_versions(2)), add=EnhanceOffer("2x · 20 steps", duplicate_of))
    (enhance_row,) = versions._host.findChildren(_AddRow)
    row = _rows(versions)[0]
    _click(qtbot, row)
    return versions, row, enhance_row


def test_up_from_the_top_version_takes_the_highlight_onto_the_enhance_row(qtbot):
    versions, row, enhance_row = _clicked_under_the_enhance_row(qtbot)

    qtbot.keyClick(row, Qt.Key.Key_Up)

    assert enhance_row._selected
    assert versions.selected_positions() == []


def test_a_shift_click_with_the_arrows_on_the_enhance_row_picks_just_the_version_clicked(qtbot):
    versions, row, enhance_row = _clicked_under_the_enhance_row(qtbot)

    qtbot.keyClick(row, Qt.Key.Key_Up)
    _click(qtbot, _rows(versions)[1], Qt.KeyboardModifier.ShiftModifier)

    assert (enhance_row._selected, versions.selected_positions()) == (False, [1]), (
        "the Enhance row is no version, so a run of versions has nowhere to start from there")


@pytest.mark.parametrize("enter", [Qt.Key.Key_Return, Qt.Key.Key_Enter],
                         ids=["Enter", "the number pad's Enter"])
def test_enter_on_the_highlighted_enhance_row_enhances_as_a_click_would(qtbot, enter):
    versions, row, _enhance_row = _clicked_under_the_enhance_row(qtbot)
    pressed = []
    versions.enhance_requested.connect(lambda: pressed.append(True))
    qtbot.keyClick(row, Qt.Key.Key_Up)

    qtbot.keyClick(row, enter)

    assert pressed == [True]


def test_enter_on_a_dimmed_enhance_row_enhances_nothing_as_a_click_would_not(qtbot):
    versions, row, enhance_row = _clicked_under_the_enhance_row(qtbot, duplicate_of=0)
    pressed = []
    versions.enhance_requested.connect(lambda: pressed.append(True))
    qtbot.keyClick(row, Qt.Key.Key_Up)

    qtbot.keyClick(row, Qt.Key.Key_Return)

    assert enhance_row._selected
    assert pressed == []


def test_down_from_the_enhance_row_picks_and_shows_the_top_version_again(qtbot):
    versions, row, enhance_row = _clicked_under_the_enhance_row(qtbot)
    shown = []
    versions.version_selected.connect(shown.append)
    qtbot.keyClick(row, Qt.Key.Key_Up)

    qtbot.keyClick(row, Qt.Key.Key_Down)

    assert shown == [0]
    assert (enhance_row._selected, versions.selected_positions()) == (False, [0])


def test_the_arrows_are_the_lists_only_while_a_version_was_the_last_thing_clicked(qtbot):
    window = QWidget()
    column = QVBoxLayout(window)
    field = QLineEdit()
    versions = EnhanceVersions()
    column.addWidget(field)
    column.addWidget(versions)
    qtbot.addWidget(window)
    versions.show_versions(_items(_versions(2)))
    window.show()
    window.activateWindow()
    QTest.qWaitForWindowActive(window)
    shown = []
    versions.version_selected.connect(shown.append)
    row = _rows(versions)[0]

    gestures.click(row, row.rect().center())
    gestures.press_key(window, Qt.Key.Key_Down)
    gestures.click(field, field.rect().center())
    gestures.press_key(window, Qt.Key.Key_Down)

    assert shown == [0, 1]


def test_a_picked_version_is_filled_with_the_familys_blue(qtbot):
    app = QApplication.instance()
    prior = app.styleSheet()
    app.setStyleSheet(build_stylesheet())
    try:
        versions = EnhanceVersions()
        qtbot.addWidget(versions)
        versions.show_versions(_items(_versions(1)))
        with qtbot.waitExposed(versions):
            versions.show()
        row = _rows(versions)[0]
        _click(qtbot, row)

        edge = row.mapTo(versions, QPoint(1, row.height() // 2))
        assert versions.grab().toImage().pixelColor(edge).name() == BLUE.name()
    finally:
        app.setStyleSheet(prior)


def _ink(label) -> str:
    label.ensurePolished()
    return label.palette().color(label.foregroundRole()).name()


def test_a_picked_versions_facts_are_written_in_white(qtbot):
    versions = EnhanceVersions()
    qtbot.addWidget(versions)
    versions.show_versions(_items(_versions(1, {"enhance_scale": 2.0})))
    row = _rows(versions)[0]
    resting = {_ink(label) for label in row._fact_cells if isinstance(label, QLabel)}

    _click(qtbot, row)

    facts = [label for label in row._fact_cells if isinstance(label, QLabel)]
    assert TEXT_PRIMARY.name() not in resting
    assert facts
    assert {_ink(label) for label in facts} == {TEXT_PRIMARY.name()}


def test_a_version_let_go_of_has_its_facts_back_in_gray(qtbot):
    versions = EnhanceVersions()
    qtbot.addWidget(versions)
    versions.show_versions(_items(_versions(1, {"enhance_scale": 2.0})))
    first, second = _rows(versions)[:2]
    resting = [_ink(label) for label in first._fact_cells if isinstance(label, QLabel)]

    _click(qtbot, first)
    _click(qtbot, second)

    assert [_ink(label) for label in first._fact_cells if isinstance(label, QLabel)] == resting


def test_delete_and_backspace_trash_the_picked_versions(qtbot):
    for key in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace):
        versions = EnhanceVersions()
        qtbot.addWidget(versions)
        versions.show_versions(_items(_versions(2)))
        asked = []
        versions.delete_requested.connect(asked.append)

        row = _rows(versions)[0]
        _click(qtbot, row)
        assert row.focusPolicy() == Qt.FocusPolicy.ClickFocus
        qtbot.keyClick(row, key)

        assert asked == [[0]]


def test_deleting_the_only_version_is_refused(qtbot):
    versions = EnhanceVersions()
    qtbot.addWidget(versions)
    versions.show_versions(_items([
        EnhanceVersion(1, "Enhance 1", {"filename": "img.png"}, {"enhance_scale": 2.0}),
    ]))
    asked = []
    versions.delete_requested.connect(asked.append)

    _rows(versions)[0].set_selected(True)
    qtbot.keyClick(versions, Qt.Key.Key_Delete)

    assert asked == [], (
        "the last version is never deleted from this list: an image with no file left is a "
        "deleted generation, and that delete is the gallery's own")


def test_delete_with_only_the_original_picked_trashes_nothing(qtbot):
    versions = EnhanceVersions()
    qtbot.addWidget(versions)
    versions.show_versions(_items(_versions(2)))
    asked = []
    versions.delete_requested.connect(asked.append)
    original = _rows(versions)[2]
    _click(qtbot, original)

    qtbot.keyClick(original, Qt.Key.Key_Delete)

    assert asked == []


def test_delete_with_the_original_picked_trashes_only_the_other_picked_versions(qtbot):
    versions = EnhanceVersions()
    qtbot.addWidget(versions)
    versions.show_versions(_items(_versions(2)))
    asked = []
    versions.delete_requested.connect(asked.append)
    newest, _, original = _rows(versions)
    _click(qtbot, newest)
    _click(qtbot, original, Qt.KeyboardModifier.ControlModifier)

    qtbot.keyClick(newest, Qt.Key.Key_Delete)

    assert asked == [[0]]


def test_a_list_shown_as_not_deletable_ignores_the_delete_key(qtbot):
    versions = EnhanceVersions()
    qtbot.addWidget(versions)
    versions.show_versions(_items(_versions(1)), deletable=False)
    asked = []
    versions.delete_requested.connect(asked.append)

    row = _rows(versions)[0]
    _click(qtbot, row)
    qtbot.keyClick(row, Qt.Key.Key_Delete)

    assert asked == []


def test_the_context_menu_deletes_what_it_opened_over(qtbot, monkeypatch):
    versions = EnhanceVersions()
    qtbot.addWidget(versions)
    versions.show_versions(_items(_versions(2)))
    asked = []
    versions.delete_requested.connect(asked.append)
    chosen = {}

    def _exec(self, _pos):
        action = self.actions()[0]
        chosen["text"] = action.text()
        chosen["enabled"] = action.isEnabled()
        return action

    monkeypatch.setattr(QMenu, "exec", _exec)

    versions._on_row_menu(1, QPoint(0, 0))

    assert chosen["enabled"] is True
    assert chosen["text"] == "Delete 1 version"
    assert asked == [[1]]


def test_the_menu_over_picks_that_include_the_original_deletes_the_others(qtbot, monkeypatch):
    versions = EnhanceVersions()
    qtbot.addWidget(versions)
    versions.show_versions(_items(_versions(2)))
    asked = []
    versions.delete_requested.connect(asked.append)
    chosen = {}

    def _exec(self, _pos):
        action = self.actions()[0]
        chosen["text"] = action.text()
        return action

    monkeypatch.setattr(QMenu, "exec", _exec)
    newest, _, original = _rows(versions)
    _click(qtbot, newest)
    _click(qtbot, original, Qt.KeyboardModifier.ControlModifier)

    versions._on_row_menu(0, QPoint(0, 0))

    assert chosen["text"] == "Delete 1 version"
    assert asked == [[0]]


def test_right_clicking_the_original_opens_no_menu(qtbot, monkeypatch):
    versions = EnhanceVersions()
    qtbot.addWidget(versions)
    versions.show_versions(_items(_versions(2)))
    opened = []
    monkeypatch.setattr(QMenu, "exec", lambda self, _pos: opened.append(self))

    versions._on_row_menu(2, QPoint(0, 0))

    assert opened == []


def test_the_menus_delete_grays_out_when_it_would_empty_the_image(qtbot, monkeypatch):
    versions = EnhanceVersions()
    qtbot.addWidget(versions)
    versions.show_versions(_items([
        EnhanceVersion(1, "Enhance 1", {"filename": "img.png"}, {"enhance_scale": 2.0}),
    ]))
    asked = []
    versions.delete_requested.connect(asked.append)
    seen = {}

    def _exec(self, _pos):
        action = next(iter(self.actions()), None)
        seen["text"] = action.text() if action else ""
        seen["enabled"] = action.isEnabled() if action else None
        return action

    monkeypatch.setattr(QMenu, "exec", _exec)

    versions._on_row_menu(0, QPoint(0, 0))

    assert seen.get("enabled") is False, (
        "grayed with the reason on it rather than left out: the answer to why this cannot be "
        "deleted is the only thing the menu can offer")
    assert "only version" in seen["text"]
    assert asked == []


def test_the_menu_says_a_videos_versions_are_not_deleted_from_here(qtbot, monkeypatch):
    versions = EnhanceVersions()
    qtbot.addWidget(versions)
    versions.show_versions(_items(_versions(1)), deletable=False)
    seen = {}

    def _exec(self, _pos):
        action = self.actions()[0]
        seen["text"] = action.text()
        seen["enabled"] = action.isEnabled()
        return action

    monkeypatch.setattr(QMenu, "exec", _exec)

    versions._on_row_menu(0, QPoint(0, 0))

    assert seen == {"text": "Delete (a video's versions can't be deleted here)",
                    "enabled": False}


def _trash(row):
    return row.findChild(QPushButton, "deleteButton")


def test_pressing_a_versions_trash_can_deletes_that_level(qtbot):
    versions = EnhanceVersions()
    qtbot.addWidget(versions)
    versions.show_versions(_items(_versions(2)))
    with qtbot.waitExposed(versions):
        versions.show()
    asked = []
    versions.delete_requested.connect(asked.append)

    qtbot.mouseClick(_trash(_rows(versions)[1]), Qt.MouseButton.LeftButton)

    assert asked == [[1]]


def test_a_versions_trash_can_deletes_only_its_own_version_whatever_is_picked(qtbot):
    versions = EnhanceVersions()
    qtbot.addWidget(versions)
    versions.show_versions(_items(_versions(2)))
    asked = []
    versions.delete_requested.connect(asked.append)
    _click(qtbot, _rows(versions)[0])
    _click(qtbot, _rows(versions)[1], Qt.KeyboardModifier.ControlModifier)

    _trash(_rows(versions)[1]).click()

    assert asked == [[1]]


def test_a_versions_trash_can_sits_beside_its_copy_button(qtbot):
    versions = EnhanceVersions()
    qtbot.addWidget(versions)
    versions.show_versions(_items(_versions(1)))
    versions.resize(600, 400)
    with qtbot.waitExposed(versions):
        versions.show()
    row = _rows(versions)[0]
    copy, reveal = (row.findChild(QPushButton, name).geometry()
                    for name in ("copyButton", "revealButton"))
    trash = _trash(row).geometry()

    assert trash.top() == copy.top()
    assert copy.right() < trash.left() < reveal.left()


def test_a_versions_trash_can_is_the_button_banks_red_can_at_the_copys_size(qtbot):
    versions = EnhanceVersions()
    qtbot.addWidget(versions)
    versions.show_versions(_items(_versions(1)))
    row = _rows(versions)[0]
    trash, copy = _trash(row), row.findChild(QPushButton, "copyButton")
    side = QSize(int(CANVAS), int(CANVAS))

    assert trash.icon().pixmap(side).toImage() == icons.delete_icon().pixmap(side).toImage()
    assert trash.iconSize() == copy.iconSize()


def test_a_version_without_a_trash_can_keeps_the_gap_after_its_copy_button(qtbot):
    gaps = []
    for listed in (_versions(1), _versions(1)[:1]):
        versions = EnhanceVersions()
        qtbot.addWidget(versions)
        versions.show_versions(_items(listed))
        versions.resize(600, 400)
        with qtbot.waitExposed(versions):
            versions.show()
        row = _rows(versions)[0]
        copy = row.findChild(QPushButton, "copyButton").geometry()
        following = _trash(row) or row.findChild(QPushButton, "revealButton")
        gaps.append(following.geometry().left() - copy.right())

    assert gaps[0] == gaps[1]


def test_an_images_only_version_has_no_trash_can(qtbot):
    versions = EnhanceVersions()
    qtbot.addWidget(versions)
    versions.show_versions(_items([
        EnhanceVersion(1, "Enhance 1", {"filename": "img.png"}, {"enhance_scale": 2.0}),
    ]))

    assert _trash(_rows(versions)[0]) is None


def test_a_videos_versions_have_no_trash_can(qtbot):
    versions = EnhanceVersions()
    qtbot.addWidget(versions)
    versions.show_versions(_items(_versions(1)), deletable=False)

    assert [_trash(row) for row in _rows(versions)] == [None, None]


def test_the_original_has_no_trash_can_beside_its_enhancements(qtbot):
    versions = EnhanceVersions()
    qtbot.addWidget(versions)
    versions.show_versions(_items(_versions(2)))

    assert [_trash(row) is not None for row in _rows(versions)] == [True, True, False]


def test_a_deletable_versions_trash_can_says_what_it_does(qtbot):
    versions = EnhanceVersions()
    qtbot.addWidget(versions)
    versions.show_versions(_items(_versions(1)))

    trash = _trash(_rows(versions)[0])
    assert trash.isEnabled()
    assert trash.toolTip() == "Delete this version"




def test_the_add_tile_leads_the_strip_and_reports_its_press(qtbot):
    versions = EnhanceVersions()
    qtbot.addWidget(versions)
    versions.show_versions(_items(_versions(1)), add=EnhanceOffer("2x · 20 steps", None))
    tiles = versions._host.findChildren((_VersionRow, _AddRow))
    assert isinstance(tiles[0], _AddRow)

    pressed = []
    versions.enhance_requested.connect(lambda: pressed.append(True))
    qtbot.mouseRelease(tiles[0], Qt.MouseButton.LeftButton)
    assert pressed == [True]


def test_a_running_enhance_takes_the_add_tiles_slot_rather_than_sitting_beside_it(qtbot):
    versions = EnhanceVersions()
    qtbot.addWidget(versions)
    versions.show_versions(_items(_versions(1)), pending=RunningEnhancement("running", None, "2x"),
                         add=EnhanceOffer("2x", None))
    tiles = versions._host.findChildren((_PendingRow, _AddRow, _VersionRow))
    assert isinstance(tiles[0], _PendingRow)
    assert not versions._host.findChildren(_AddRow)


def _share_painted(image, color) -> float:
    painted = sum(1 for y in range(image.height()) for x in range(image.width())
                  if image.pixelColor(x, y) == color)
    return painted / max(1, image.width() * image.height())


def test_the_add_rows_thumbnail_is_the_yellow_press_and_the_row_beside_it_is_not(qtbot):
    versions = EnhanceVersions()
    qtbot.addWidget(versions)
    versions.show_versions(_items(_versions(1)), add=EnhanceOffer("2x · 20 steps", None))
    versions.resize(420, 600)
    versions.show()
    QApplication.processEvents()
    (add_row,) = versions._host.findChildren(_AddRow)
    image = add_row.grab().toImage()
    thumbnail = add_row._thumbnail.geometry()
    beside = image.copy(thumbnail.right() + 1, 0, image.width() - thumbnail.right() - 1,
                        image.height())

    assert add_row._thumbnail.size() == versions._rows[0]._thumbnail.size()
    assert _share_painted(image.copy(thumbnail), YELLOW) > 0.5
    assert _share_painted(beside, YELLOW) == 0


def test_the_add_tiles_plus_is_drawn_big_in_its_tile(qtbot):
    versions = EnhanceVersions()
    qtbot.addWidget(versions)
    versions.show_versions(_items(_versions(1)), add=EnhanceOffer("2x · 20 steps", None))
    (add_row,) = versions._host.findChildren(_AddRow)
    plus = add_row._thumbnail.pixmap().toImage()

    inked = sum(1 for y in range(plus.height()) for x in range(plus.width())
                if plus.pixelColor(x, y).alpha() > 128)
    assert inked >= add_row._thumbnail.width() * add_row._thumbnail.height() // 12, (
        "drawn, like the Gallery pane buttons' plus, not typed")


def test_an_image_with_nothing_yet_still_gets_the_tile(qtbot):
    versions = EnhanceVersions()
    qtbot.addWidget(versions)
    versions.show_versions([], add=EnhanceOffer("2x", None))
    assert not versions.isHidden()
    assert versions._host.findChildren(_AddRow)


def test_the_tile_dims_when_it_would_only_duplicate_a_version(qtbot):
    versions = EnhanceVersions()
    qtbot.addWidget(versions)
    versions.show_versions(_items(_versions(1)), add=EnhanceOffer("2x · 20 steps", 0))
    (add_row,) = versions._host.findChildren(_AddRow)

    pressed = []
    versions.enhance_requested.connect(lambda: pressed.append(True))
    qtbot.mouseRelease(add_row, Qt.MouseButton.LeftButton)
    assert pressed == []
    assert "already has a version" in add_row.toolTip()


def test_hovering_the_dimmed_tile_outlines_the_version_it_would_duplicate_in_white(qtbot):
    versions = EnhanceVersions()
    qtbot.addWidget(versions)
    versions.show_versions(_items(_versions(2)), add=EnhanceOffer("2x", 1))
    (add_row,) = versions._host.findChildren(_AddRow)
    duplicate = versions._rows[1]._thumbnail
    point = QPointF(add_row.rect().center())
    resting = duplicate.styleSheet()

    QApplication.sendEvent(add_row, QEnterEvent(point, point, QPointF(add_row.mapToGlobal(point))))
    outline = duplicate.grab().toImage().pixelColor(0, duplicate.height() // 2).name()
    QApplication.sendEvent(add_row, QEvent(QEvent.Type.Leave))

    assert resting == ""
    assert outline == TEXT_PRIMARY.name()
    assert duplicate.styleSheet() == ""


def test_a_version_carries_its_settings_as_a_drag_payload():
    params = {"enhance_scale": 3.0, "enhance_steps": 40, "enhance_denoise": 0.35}
    assert params_from_mime(enhance_version_mime(params)) == params


def test_a_foreign_drag_carries_nothing_this_panel_wants():
    mime = QMimeData()
    mime.setText("just some text")
    assert params_from_mime(mime) is None


@pytest.fixture
def version_drags(monkeypatch):
    """The drags a version row begins; QDrag stands aside because the real drag loop is modal and waits on a mouse."""
    started = []

    class _Drag:
        def __init__(self, source):
            self.source = source
            self.mime = None
            self.pixmap = None
            started.append(self)

        def setMimeData(self, mime):
            self.mime = mime

        def setPixmap(self, pixmap):
            self.pixmap = pixmap

        def exec(self, _action):
            return None

    monkeypatch.setattr(drag_thumbnail, "QDrag", _Drag)
    return started


def _an_image(path, size=(16, 16)):
    Image.new("RGB", size, (200, 80, 40)).save(path)
    return path


def test_the_dragged_version_trails_the_cursor(qtbot, tmp_path, version_drags):
    thumbnail = _VersionRow(_versions(1, {"enhance_scale": 2.0})[0], 0,
                     _an_image(tmp_path / "e1.png"))
    qtbot.addWidget(thumbnail)

    qtbot.mousePress(thumbnail, Qt.MouseButton.LeftButton, pos=QPoint(2, 2))
    qtbot.mouseMove(thumbnail, QPoint(90, 90))

    (drag,) = version_drags
    assert not drag.pixmap.isNull()
    assert params_from_mime(drag.mime) == {"enhance_scale": 2.0}


def test_a_small_move_on_a_version_is_a_click_not_a_drag(qtbot, tmp_path, version_drags):
    thumbnail = _VersionRow(_versions(1, {"enhance_scale": 2.0})[0], 0,
                     _an_image(tmp_path / "e1.png"))
    qtbot.addWidget(thumbnail)

    qtbot.mousePress(thumbnail, Qt.MouseButton.LeftButton, pos=QPoint(2, 2))
    qtbot.mouseMove(thumbnail, QPoint(3, 3))

    assert version_drags == [], (
        "the other drag tests move far past the threshold and cannot see it go: without it a click "
        "that wobbles a pixel picks the row up in place of selecting it")


def test_a_big_versions_thumbnail_drags_at_the_shared_size(qtbot, tmp_path, version_drags):
    thumbnail = _VersionRow(_versions(1, {"enhance_scale": 2.0})[0], 0,
                     _an_image(tmp_path / "big.png", (1024, 768)))
    qtbot.addWidget(thumbnail)

    qtbot.mousePress(thumbnail, Qt.MouseButton.LeftButton, pos=QPoint(2, 2))
    qtbot.mouseMove(thumbnail, QPoint(90, 90))

    (drag,) = version_drags
    assert max(drag.pixmap.width(), drag.pixmap.height()) == THUMBNAIL_MAX


def test_a_missing_file_drags_without_a_thumbnail(qtbot, monkeypatch):
    class _RecordingDrag:
        def __init__(self, source):
            pass

        def setMimeData(self, mime):
            pass

        def setPixmap(self, pixmap):
            raise AssertionError("nothing to show, so nothing should be set")

        def exec(self, _action):
            return None

    monkeypatch.setattr(drag_thumbnail, "QDrag", _RecordingDrag)

    thumbnail = _VersionRow(_versions(1, {"enhance_scale": 2.0})[0], 0, None)
    qtbot.addWidget(thumbnail)
    qtbot.mousePress(thumbnail, Qt.MouseButton.LeftButton, pos=QPoint(2, 2))
    qtbot.mouseMove(thumbnail, QPoint(90, 90))



def test_a_running_enhance_leads_the_strip(qtbot):
    versions = EnhanceVersions()
    qtbot.addWidget(versions)
    versions.show_versions(_items(_versions(1)), RunningEnhancement("running", None, "2x"))
    tiles = versions._host.findChildren((_PendingRow, _VersionRow))
    assert isinstance(tiles[0], _PendingRow)


def test_a_first_enhance_brings_the_strip_out_on_its_own(qtbot):
    versions = EnhanceVersions()
    qtbot.addWidget(versions)
    versions.show_versions(_items(_versions(0)), RunningEnhancement("queued", None, "2x"))
    assert not versions.isHidden()


def test_the_live_tile_names_the_settings_it_is_running_at(qtbot):
    versions = EnhanceVersions()
    qtbot.addWidget(versions)
    versions.show_versions(_items(_versions(1)),
                         RunningEnhancement("queued", None, "3x · 40 steps · 0.35 redraw"))
    texts = [lbl.text().replace("\u200b", "")
             for lbl in versions._pending.findChildren(QLabel)]
    assert "Queued…" in texts
    assert any("40 steps" in t and "0.35 redraw" in t for t in texts)
    assert "3x · 40 steps · 0.35 redraw" in versions._pending.toolTip()


def test_a_new_frame_updates_the_tile_without_a_rebuild(qtbot):
    versions = EnhanceVersions()
    qtbot.addWidget(versions)
    versions.show_versions(_items(_versions(1)), RunningEnhancement("running", None, "2x"))
    thumbnail = versions._pending

    assert versions.update_pending(RunningEnhancement("running", b"not a real png", "2x")) is True
    assert versions._pending is thumbnail

    assert versions.update_pending(None) is False, (
        "a run starting or ending changes the strip's shape, which only a rebuild can do, so the "
        "caller is told rather than left with a stale strip")


def _held(mime) -> tuple:
    return (Qt.DropAction.CopyAction, mime, Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier)


def _brought_over(pane, mime):
    """A drag of ``mime`` brought over ``pane`` and held there. Qt hands a
    drag's later events to the widget that took its first."""
    QApplication.sendEvent(pane, QDragEnterEvent(QPoint(5, 5), *_held(mime)))
    QApplication.sendEvent(pane, QDragMoveEvent(QPoint(5, 5), *_held(mime)))


def _dropped_on(pane, mime):
    _brought_over(pane, mime)
    QApplication.sendEvent(pane, QDropEvent(QPointF(5, 5), *_held(mime)))


def test_dropping_a_version_absorbs_its_settings(qtbot):
    pane, edits = _panel(qtbot)
    pane._auto.setChecked(True)
    edits.clear()
    # Held in a local: a QMimeData freed mid-event takes the handler with it.
    mime = enhance_version_mime({"enhance_scale": 3.0, "enhance_steps": 40,
                               "enhance_denoise": 0.35})

    _dropped_on(pane, mime)

    settings = pane.settings()
    assert settings.params["enhance_scale"] == 3.0
    assert settings.params["enhance_steps"] == 40
    assert settings.params["enhance_denoise"] == 0.35
    assert settings.auto is True, (
        "the drop says what to enhance at, not whether to keep enhancing")
    assert edits
    assert edits[-1] == settings


def test_a_dropped_version_leaves_the_panel_at_exactly_what_that_version_ran_with(qtbot):
    pane, _edits = _panel(qtbot)
    pane.show_settings(EnhanceSettings(params={
        "enhance_scale": 3.0, "enhance_detail_fixes": {"hands": 0.3},
        "enhance_fix_prompts": {"hands": {"prompt": "open palms", "avoid": "fists"}}}))
    ran = {"enhance_scale": 2.0, "enhance_detail_fixes": {"hands": 0.45}}
    mime = enhance_version_mime(ran)

    _dropped_on(pane, mime)

    assert full_settings(pane.settings().params) == full_settings(ran)


def _in_the_app(qtbot, pane):
    host = QWidget()
    QVBoxLayout(host).addWidget(pane)
    host.setStyleSheet(build_stylesheet())
    qtbot.addWidget(host)
    host.resize(420, 700)
    with qtbot.waitExposed(host):
        host.show()
    return pane


def _drop_styles_worn(pane) -> set:
    heading = next(label for label in pane.findChildren(QLabel) if label.text() == "Enhance")
    settings = pane.findChild(QScrollArea).geometry()
    image = pane.grab().toImage()
    return {worn(image, pane.rect(), spot) for spot in (
        QPoint(heading.geometry().right() + 10, heading.geometry().center().y()),
        QPoint(settings.left() + 5, settings.bottom() - 5))}


def test_the_panel_lights_while_a_version_it_would_take_is_dragged(qtbot):
    pane = _in_the_app(qtbot, _panel(qtbot)[0])
    assert _drop_styles_worn(pane) == {None}

    under_way.started.emit(enhance_version_mime({"enhance_scale": 3.0}), None)

    assert _drop_styles_worn(pane) == {LIT}
    under_way.ended.emit()


def test_the_panel_under_the_drag_lights_one_step_lighter(qtbot):
    pane = _in_the_app(qtbot, _panel(qtbot)[0])
    mime = enhance_version_mime({"enhance_scale": 3.0})
    under_way.started.emit(mime, None)

    _brought_over(pane, mime)

    assert _drop_styles_worn(pane) == {AIMED}
    QApplication.sendEvent(pane, QDragLeaveEvent())
    under_way.ended.emit()


def test_the_panel_stays_as_it_is_while_anything_else_is_dragged(qtbot):
    pane = _in_the_app(qtbot, _panel(qtbot)[0])
    mime = QMimeData()
    mime.setText("just some text")

    under_way.started.emit(mime, None)

    assert _drop_styles_worn(pane) == {None}
    under_way.ended.emit()


def test_the_strip_folds_away_like_the_form_sections_above_it(qtbot):
    versions = EnhanceVersions()
    qtbot.addWidget(versions)
    versions.show_versions(_items(_versions(1)), add=EnhanceOffer("2x", None))

    (section,) = versions.findChildren(CollapsibleSection)
    assert section._header.text() == "Enhancements"
    assert not versions.is_collapsed()

    versions.set_collapsed(True)
    assert versions.is_collapsed()
    assert section.content().isHidden()


def test_folding_survives_a_rebuild_for_another_image(qtbot):
    versions = EnhanceVersions()
    qtbot.addWidget(versions)
    versions.set_collapsed(True)
    versions.show_versions(_items(_versions(2)), add=EnhanceOffer("2x", None))
    assert versions.is_collapsed()


def test_a_narrow_row_puts_its_facts_under_the_thumbnail(qtbot):
    (version,) = _versions(1)[:1]
    row = _VersionRow(version, 0, None)
    host = QWidget()
    column = QVBoxLayout(host)
    column.setContentsMargins(0, 0, 0, 0)
    column.addWidget(row)
    qtbot.addWidget(host)
    host.show()

    side_by_side = row._thumbnail.sizeHint().width() + row._facts.minimumSize().width()
    assert row.minimumSizeHint().width() < side_by_side, (
        "side by side, a thumbnail and its facts would be the widest thing in the tab and would "
        "decide how narrow the Generate pane can be dragged before its settings scroll sideways; "
        "stacked, the row asks for the wider of the two rather than their sum")

    host.resize(side_by_side + 60, 400)
    QApplication.processEvents()
    assert row._title.x() > row._thumbnail.x() + row._thumbnail.width()
    assert row._title.y() < row._thumbnail.y() + row._thumbnail.height()

    host.resize(row.minimumSizeHint().width(), 400)
    QApplication.processEvents()
    assert row._title.y() >= row._thumbnail.y() + row._thumbnail.height()


def test_the_panels_captions_use_plain_words(qtbot):
    pane, _edits = _panel(qtbot)
    captions = [w.text() for w in pane.findChildren(QLabel)]
    assert {"Model", "Upscaler", "Scale", "Steps", "Redraw Amount"} <= set(captions)
    assert not any("Denoise" in caption or caption.endswith(":") for caption in captions)


def test_a_number_on_the_panel_says_its_good_range(qtbot):
    pane, _edits = _panel(qtbot)
    assert "Good range: 0.1\u20130.2." in pane._denoise.toolTip()
    assert "Good range: 1.5\u20132." in pane._scale.toolTip()


def test_each_fixs_button_opens_its_prompts_over_the_enhance_pane_alone_leaving_the_window_usable(qtbot):
    pane, _edits = _panel(qtbot)
    pane.show()
    hands = next(part for part in part_table() if part.name == "hands")

    pane._fix_prompt_buttons["hands"].click()

    window = pane._fix_prompt_windows["hands"]
    assert window.isVisible()
    assert window.windowModality() == Qt.WindowModality.NonModal
    assert window.windowFlags() & Qt.WindowType.FramelessWindowHint
    assert window.geometry() == QRect(pane.mapToGlobal(QPoint(0, 0)), pane.size())
    assert "Hands fix prompts" in [label.text() for label in window.findChildren(QLabel)]
    assert (window.prompts()["prompt"], window.prompts()["avoid"]) == (hands.prompt, hands.avoid)


def test_a_fixs_prompts_stay_over_the_enhance_pane_as_the_window_moves_and_its_border_is_dragged(qtbot):
    host = QWidget()
    qtbot.addWidget(host)
    column = QVBoxLayout(host)
    pane, _edits = _panel(qtbot)
    column.addWidget(QWidget(), 1)
    column.addWidget(pane)
    host.resize(900, 900)
    host.show()
    pane._fix_prompt_buttons["hands"].click()
    window = pane._fix_prompt_windows["hands"]

    host.move(host.pos() + QPoint(40, 30))
    pane.setFixedHeight(pane.height() + 50)

    qtbot.waitUntil(lambda: window.geometry()
                    == QRect(pane.mapToGlobal(QPoint(0, 0)), pane.size()))


def test_a_fixs_prompts_fit_an_enhance_pane_dragged_as_short_as_it_goes(qtbot):
    pane, _edits = _panel(qtbot)
    pane.setStyleSheet(build_stylesheet() + pane.styleSheet())
    pane.resize(700, pane.minimumSizeHint().height())
    pane.show()

    pane._fix_prompt_buttons["hands"].click()

    window = pane._fix_prompt_windows["hands"]
    assert window.geometry() == QRect(pane.mapToGlobal(QPoint(0, 0)), pane.size())
    for field in (*window.positive.boxes(), *window.negative.boxes()):
        assert field.height() >= 2 * field.fontMetrics().lineSpacing()


def test_a_fixs_prompts_window_highlights_a_thing_in_both_of_its_prompts(qtbot):
    pane, _edits = _panel(qtbot)
    pane._fix_prompt_buttons["hands"].click()
    window = pane._fix_prompt_windows["hands"]

    window.positive.boxes()[0].setPlainText("red cat")
    window.negative.boxes()[0].setPlainText("red cat")

    assert problem_to_resolve(window.positive.boxes()) == RESOLVE_IN_BOTH_PROMPTS


def test_each_fixs_edit_button_is_the_square_the_buttons_above_the_gallery_are(qtbot):
    pane, _edits = _panel(qtbot)

    for button in pane._fix_prompt_buttons.values():
        assert button.size() == QSize(BUTTON_SIZE_HUD, BUTTON_SIZE_HUD)


def test_each_fixs_edit_button_checkbox_name_and_value_sit_inside_one_thin_gray_border(qtbot):
    pane, _edits = _panel(qtbot)
    pane.setStyleSheet(build_stylesheet() + pane.styleSheet())
    pane.resize(700, pane.sizeHint().height())
    pane.show()
    drawn = pane.grab().toImage()

    frames = set()
    for name, button in pane._fix_prompt_buttons.items():
        frame = button.parentWidget()
        assert frame.isAncestorOf(pane._fix_checks[name])
        assert frame.isAncestorOf(pane._fixes[name])
        top_edge = frame.mapTo(pane, QPoint(frame.width() // 2, 0))
        assert drawn.pixelColor(top_edge).name() == BORDER_SUBTLE.name()
        frames.add(frame)
    assert len(frames) == len(pane._fix_prompt_buttons)


def test_a_fixs_prompts_offer_its_lora_and_strength_and_ok_keeps_them(qtbot, monkeypatch,
                                                                    titled_models):
    monkeypatch.setattr(enhance_pane_module, "list_lora_files",
                        lambda fallback, **terms: ["None", "my_hands.safetensors"])
    titled_models({"my_hands": "My Hands v1"})
    pane, edits = _panel(qtbot)
    pane._fix_prompt_buttons["hands"].click()
    window = pane._fix_prompt_windows["hands"]

    assert [window.lora.itemText(i) for i in range(window.lora.count())] == [
        "None", "My Hands v1"]
    window.lora.setCurrentIndex(window.lora.findData("my_hands.safetensors"))
    window.strength.setValue(0.7)
    window.accept()

    kept = edits[-1].params["enhance_fix_prompts"]["hands"]
    assert (kept["lora"], kept["strength"]) == ("my_hands.safetensors", 0.7)


def test_a_fixs_prompts_offer_only_the_loras_the_enhance_model_can_run(qtbot, installed_models):
    installed_models.add("loras", "an_xl_fix.safetensors", arch="sdxl", lora=True)
    installed_models.add("loras", "a_15_fix.safetensors", arch="sd15", lora=True)
    pane, _edits = _panel(qtbot)
    pane._fix_prompt_buttons["hands"].click()
    lora = pane._fix_prompt_windows["hands"].lora

    offered = {lora.itemData(row) for row in range(lora.count())}
    assert {"an_xl_fix.safetensors", "a_15_fix.safetensors"} & offered == {
        "an_xl_fix.safetensors"}


def test_a_fixs_prompts_offer_its_own_fixs_loras_and_no_other_fixs(qtbot, installed_models):
    hands = os.path.join("fixes", "hands 2026-10-19 1444.safetensors")
    for name in ("an_xl_look.safetensors", hands,
                 os.path.join("fixes", "faces 2026-10-20 0910.safetensors")):
        installed_models.add("loras", name, arch="sdxl", lora=True)
    pane, _edits = _panel(qtbot)
    pane._fix_prompt_buttons["hands"].click()
    lora = pane._fix_prompt_windows["hands"].lora

    assert {lora.itemData(row) for row in range(lora.count())} == {
        "None", "an_xl_look.safetensors", hands}


_HANDS_LORA = os.path.join("fixes", "hands 2026-10-19 1444.safetensors")
_ITS_TWO_WAYS_OUT = (
    "A LoRA works best on the model it was trained on. On another model it can do little or make "
    "the fix look wrong.\nTo fix this, either turn off the Hands fix or change Model to trained_on.")
_MODEL_SET_ELSEWHERE_SAID = ("The Hands fix's LoRA was trained on trained_on, but Model is set to "
                             "picked.\n" + _ITS_TWO_WAYS_OUT)
_SOME_MADE_ELSEWHERE_SAID = ("The Hands fix's LoRA was trained on trained_on, but some of the source "
                             "images were made with picked.\n" + _ITS_TWO_WAYS_OUT)
_SOURCE_MADE_ELSEWHERE_SAID = ("The Hands fix's LoRA was trained on trained_on, but the source image "
                               "was made with picked.\n" + _ITS_TWO_WAYS_OUT)


@pytest.fixture
def hands_trained_on(qtbot, monkeypatch, tmp_path, installed_models):
    for model in ("picked.safetensors", "trained_on.safetensors"):
        installed_models.add("checkpoints", model, arch="sdxl")
    monkeypatch.setattr(config, "FIX_TRAINING_DIR", tmp_path / "fix training")
    work = tmp_path / "fix training" / "hands"
    work.mkdir(parents=True)
    (work / "job.json").write_text(json.dumps({
        "part": "hands", "output_name": "hands 2026-10-19 1444",
        "base_model": str(installed_models.root / "models" / "checkpoints"
                          / "trained_on.safetensors")}), encoding="utf-8")
    pane, edits = _panel(qtbot)

    def shown(fixes, model="picked.safetensors"):
        pane.show_settings(EnhanceSettings(auto=False, params={
            "checkpoint": model, "enhance_detail_fixes": fixes,
            "enhance_fix_prompts": {"hands": {"lora": _HANDS_LORA}}}))
        return pane, edits

    return shown


def test_a_ticked_fixs_lora_trained_on_another_model_warns_beside_the_model(hands_trained_on):
    pane, _edits = hands_trained_on({"hands": 0.45})

    assert (pane._model_warning.isHidden(), pane._model_warning.toolTip()) == (
        False, _MODEL_SET_ELSEWHERE_SAID)


def test_clicking_the_models_warning_leaves_the_choice_of_model_or_fix_to_the_user(
        qtbot, hands_trained_on):
    pane, edits = hands_trained_on({"hands": 0.45})
    made_before = len(edits)

    qtbot.mouseClick(pane._model_warning, Qt.MouseButton.LeftButton)

    assert len(edits) == made_before
    assert pane._model.currentData() == "picked.safetensors"
    assert not pane._model_warning.isHidden()
    assert pane._model_warning.cursor().shape() != Qt.CursorShape.PointingHandCursor


def test_no_model_warning_while_the_fix_is_off_or_the_model_is_the_one_it_was_trained_on(
        hands_trained_on):
    assert hands_trained_on({})[0]._model_warning.isHidden()
    assert hands_trained_on({"hands": 0.45}, "trained_on.safetensors")[0]._model_warning.isHidden()


def _made_by(model: str, *, file: str = "one.png") -> dict:
    return {"prompt_id": file, "workflow_name": "sdxl_t2i", "status": "completed",
            "output_files": json.dumps([{"filename": file}]),
            "params_json": json.dumps({"checkpoint": model})}


def test_matching_the_source_warns_not_while_the_images_in_front_were_made_by_the_fixs_model(
        hands_trained_on):
    pane, _edits = hands_trained_on({"hands": 0.45}, MATCH_SOURCE_MODEL)

    pane.show_images_in_front([_made_by("trained_on.safetensors"),
                                _made_by("picked.safetensors", file="two.mp4")])

    assert pane._model_warning.isHidden()


def test_matching_the_source_warns_while_a_picked_image_is_made_by_another_model(
        hands_trained_on):
    pane, _edits = hands_trained_on({"hands": 0.45}, MATCH_SOURCE_MODEL)

    pane.show_images_in_front([_made_by("trained_on.safetensors"),
                                _made_by("picked.safetensors", file="two.png")])

    assert (pane._model_warning.isHidden(), pane._model_warning.toolTip()) == (
        False, _SOME_MADE_ELSEWHERE_SAID)


def _folder(*rows) -> SettingsGroup:
    return SettingsGroup("a folder", "A folder", list(rows))


@pytest.mark.parametrize(("folder", "hidden"), [
    (_folder(_made_by("trained_on.safetensors"), _made_by("trained_on.safetensors", file="b.png")),
     True),
    (_folder(_made_by("picked.safetensors")), False)])
def test_matching_the_source_holds_the_fixs_model_against_the_folders_own(
        hands_trained_on, folder, hidden):
    pane, _edits = hands_trained_on({"hands": 0.45}, MATCH_SOURCE_MODEL)

    pane.show_images_in_front([], folder)

    assert pane._model_warning.isHidden() is hidden
    assert hidden or pane._model_warning.toolTip() == _SOURCE_MADE_ELSEWHERE_SAID


_NO_GUARANTEE_SAID = ("The Hands fix's LoRA was trained on trained_on, and there's no guarantee "
                      "the source images here were made with it.\n" + _ITS_TWO_WAYS_OUT)


@pytest.mark.parametrize("folder", [
    _folder(_made_by("trained_on.safetensors"), _made_by("picked.safetensors", file="b.png")),
    None])
def test_matching_the_source_in_a_folder_of_several_models_or_a_collection_says_there_is_no_guarantee(
        hands_trained_on, folder):
    pane, _edits = hands_trained_on({"hands": 0.45}, MATCH_SOURCE_MODEL)

    pane.show_images_in_front([], folder)

    assert (pane._model_warning.isHidden(), pane._model_warning.toolTip()) == (
        False, _NO_GUARANTEE_SAID)


def test_clicking_the_no_guarantee_warning_leaves_the_model_as_it_is(qtbot, hands_trained_on):
    pane, edits = hands_trained_on({"hands": 0.45}, MATCH_SOURCE_MODEL)
    pane.show_images_in_front([])
    made_before = len(edits)

    qtbot.mouseClick(pane._model_warning, Qt.MouseButton.LeftButton)

    assert len(edits) == made_before
    assert pane._model.currentData() == MATCH_SOURCE_MODEL


_CAPTIONS = ("Model", "Upscaler", "Scale", "Steps", "Redraw Amount")


def _caption_lefts(pane) -> dict[str, int]:
    return {label.text(): label.mapTo(pane, QPoint()).x()
            for label in pane.findChildren(QLabel) if label.text() in _CAPTIONS}


def test_the_models_warning_sits_left_of_its_caption_with_the_captions_in_line(
        hands_trained_on):
    pane, _edits = hands_trained_on({"hands": 0.45})
    _laid_out_at(pane, 2000)

    lefts = _caption_lefts(pane)
    caption = next(label for label in pane.findChildren(QLabel) if label.text() == "Model")
    mark = pane._model_warning
    assert mark.mapTo(pane, QPoint()).x() + mark.width() <= lefts["Model"]
    assert _rows_of(pane, mark) & _rows_of(pane, caption)
    assert lefts["Model"] == lefts["Upscaler"] == lefts["Scale"]


def test_the_captions_stay_where_they_are_while_the_models_warning_is_hidden(hands_trained_on):
    pane, _edits = hands_trained_on({"hands": 0.45})
    _laid_out_at(pane, 2000)
    warned = _caption_lefts(pane)

    hands_trained_on({})
    _laid_out_at(pane, 2000)

    assert pane._model_warning.isHidden()
    assert _caption_lefts(pane) == warned


def test_a_caption_moved_onto_a_line_of_its_own_keeps_in_line_with_the_others(hands_trained_on):
    pane, _edits = hands_trained_on({"hands": 0.45})

    _laid_out_at(pane, pane.minimumSizeHint().width())

    assert len(set(_caption_lefts(pane).values())) == 1


_STYLE_SAID = ("Example Style 1.0's trigger word, exmplstyle, isn't in the Positive Prompt. "
               "Click to add it.")


@pytest.fixture
def worded_fix(qtbot, monkeypatch, worded_loras, titled_models):
    monkeypatch.setattr(enhance_pane_module, "list_lora_files",
                        lambda fallback, **terms: ["None", "example_style.safetensors"])
    worded_loras({"example_style": ["exmplstyle"]})
    titled_models({"example_style": "Example Style 1.0"})
    pane, _edits = _panel(qtbot)
    pane._fix_prompt_buttons["hands"].click()
    window = pane._fix_prompt_windows["hands"]
    window.positive.boxes()[0].setPlainText("a close-up")
    window.lora.setCurrentIndex(window.lora.findData("example_style.safetensors"))
    return window


def test_a_fixs_lora_whose_trigger_word_its_prompt_lacks_warns_beside_its_prompt_and_lora(
        worded_fix):
    marks = (worded_fix.prompt_warning, worded_fix.lora_warning)

    assert [(mark.isHidden(), mark.toolTip()) for mark in marks] == [(False, _STYLE_SAID)] * 2


@pytest.mark.parametrize("mark", ["prompt_warning", "lora_warning"])
def test_clicking_a_fixs_trigger_word_warning_puts_the_word_at_the_start_of_its_prompt(
        qtbot, worded_fix, mark):
    qtbot.mouseClick(getattr(worded_fix, mark), Qt.MouseButton.LeftButton)

    assert worded_fix.positive.value() == "exmplstyle, a close-up"
    assert worded_fix.prompt_warning.isHidden()
    assert worded_fix.lora_warning.isHidden()


def test_a_fixs_prompt_is_one_prompt_however_many_lines_of_dashes_it_holds(worded_fix):
    worded_fix.positive.boxes()[0].setPlainText("exmplstyle, part one\n---\npart two")

    assert worded_fix.prompt_warning.isHidden()
    assert worded_fix.lora_warning.isHidden()


def test_a_fixs_trigger_word_warning_goes_once_its_lora_is_put_on_none(worded_fix):
    worded_fix.lora.setCurrentIndex(worded_fix.lora.findData("None"))

    assert worded_fix.prompt_warning.isHidden()
    assert worded_fix.lora_warning.isHidden()


def test_a_fixs_trigger_word_warnings_sit_left_of_the_prompt_and_lora_captions(worded_fix):
    worded_fix.resize(700, 600)
    worded_fix.layout().activate()

    for mark, caption in ((worded_fix.prompt_warning, "Positive Prompt"),
                          (worded_fix.lora_warning, "LoRA")):
        label = next(label for label in worded_fix.findChildren(QLabel)
                     if label.text() == caption)
        left_of_label = label.mapTo(worded_fix, QPoint()).x()
        assert mark.mapTo(worded_fix, QPoint()).x() + mark.width() <= left_of_label
        assert _rows_of(worded_fix, mark) & _rows_of(worded_fix, label)


def test_a_fixs_lora_strength_says_what_range_works_well_as_every_forms_does(qtbot):
    pane, _edits = _panel(qtbot)
    pane._fix_prompt_buttons["hands"].click()
    window = pane._fix_prompt_windows["hands"]

    assert "Good range: 0.6\u20131.2." in window.strength.toolTip()
    assert window.strength.toolTip().startswith("How hard the LoRA pulls.")


def _fix_window_laid_out_at(window, width: int) -> dict:
    window.resize(width, 600)
    window.layout().activate()
    buttons = window.findChild(QDialogButtonBox)
    return {"ok": buttons.button(QDialogButtonBox.StandardButton.Ok),
            "cancel": buttons.button(QDialogButtonBox.StandardButton.Cancel),
            "train": window.training.train, "prompt_height": window.positive.height()}


def _rows_of(window, widget) -> set[int]:
    top = widget.mapTo(window, QPoint()).y()
    return set(range(top, top + widget.height()))


def test_a_fixs_lora_controls_take_a_row_of_their_own_rather_than_squeeze_any_button(qtbot):
    pane, _edits = _panel(qtbot)
    pane._fix_prompt_buttons["hands"].click()
    window = pane._fix_prompt_windows["hands"]

    wide = _fix_window_laid_out_at(window, 1600)
    assert _rows_of(window, wide["ok"]) & _rows_of(window, wide["train"])
    tall_prompts = wide["prompt_height"]

    narrow = _fix_window_laid_out_at(window, 420)
    assert min(_rows_of(window, narrow["ok"])) > max(_rows_of(window, narrow["train"]))
    assert narrow["prompt_height"] < tall_prompts
    for button in (narrow["ok"], narrow["cancel"], narrow["train"]):
        assert button.width() >= button.sizeHint().width()


def test_train_in_a_fixs_prompts_asks_for_that_fix_to_be_trained(qtbot):
    pane, _edits = _panel(qtbot)
    pane._fix_prompt_buttons["hands"].click()
    window = pane._fix_prompt_windows["hands"]

    with qtbot.waitSignal(pane.fix_training_requested) as asked:
        window.training.train.click()

    assert asked.args == ["hands"]


def _fix_images(monkeypatch, tmp_path, *names):
    monkeypatch.setattr(config, "FIX_IMAGES_DIR", tmp_path)
    monkeypatch.setattr(config, "FIX_TRAINING_DIR", tmp_path / "fix training")
    if names:
        (tmp_path / "hands").mkdir()
    for name in names:
        (tmp_path / "hands" / name).write_bytes(b"")
    return tmp_path / "hands"


def test_beside_train_a_fixs_prompts_say_how_many_images_its_folder_holds(
        qtbot, monkeypatch, tmp_path):
    folder = _fix_images(monkeypatch, tmp_path, "one.jpg", "two.png", "notes.txt")
    pane, _edits = _panel(qtbot)

    pane._fix_prompt_buttons["hands"].click()

    window = pane._fix_prompt_windows["hands"]
    assert window.training.images.text() == "2 images"
    assert window.training.images.toolTip() == str(folder)


def test_a_fixs_images_are_counted_again_each_time_its_prompts_come_to_the_front(
        qtbot, monkeypatch, tmp_path):
    folder = _fix_images(monkeypatch, tmp_path, "one.jpg")
    pane, _edits = _panel(qtbot)
    pane._fix_prompt_buttons["hands"].click()
    window = pane._fix_prompt_windows["hands"]
    assert window.training.images.text() == "1 image"

    (folder / "two.jpg").write_bytes(b"")
    QApplication.sendEvent(window, QEvent(QEvent.Type.WindowActivate))

    assert window.training.images.text() == "2 images"


def test_show_in_explorer_opens_a_fixs_images_folder_making_it_first_if_need_be(
        qtbot, monkeypatch, tmp_path):
    folder = _fix_images(monkeypatch, tmp_path)
    opened = []
    monkeypatch.setattr(training_controls_module, "open_in_explorer", opened.append)
    pane, _edits = _panel(qtbot)
    pane._fix_prompt_buttons["hands"].click()
    window = pane._fix_prompt_windows["hands"]
    assert window.training.images.text() == "0 images"

    window.training.folder.click()

    assert opened == [folder]
    assert folder.is_dir()


def test_a_fixs_train_button_says_how_its_training_is_going_until_it_ends(qtbot):
    pane, _edits = _panel(qtbot)
    pane.show_fix_training("hands", "Training 40%")
    pane._fix_prompt_buttons["hands"].click()
    window = pane._fix_prompt_windows["hands"]
    assert (window.training.train.text(), window.training.train.isEnabled()) == ("Training 40%", False)

    pane.show_fix_training("hands", None)

    assert (window.training.train.text(), window.training.train.isEnabled()) == ("Train", True)


def test_a_trained_fixs_button_says_retrain_grayed_until_its_images_change(
        qtbot, monkeypatch, tmp_path):
    folder = _fix_images(monkeypatch, tmp_path, "one.jpg")
    record = tmp_path / "fix training" / "hands" / "trained.json"
    record.parent.mkdir(parents=True)
    record.write_text(json.dumps({"photo_stamps": fix_training.image_stamps(
        parts.part_named("hands"))}), encoding="utf-8")
    pane, _edits = _panel(qtbot)
    pane._fix_prompt_buttons["hands"].click()
    window = pane._fix_prompt_windows["hands"]
    assert (window.training.train.text(), window.training.train.isEnabled()) == ("Retrain", False)

    (folder / "two.jpg").write_bytes(b"")
    QApplication.sendEvent(window, QEvent(QEvent.Type.WindowActivate))

    assert (window.training.train.text(), window.training.train.isEnabled()) == ("Retrain", True)


def test_train_says_it_draws_on_the_shared_folder_only_for_a_fix_that_does(qtbot, monkeypatch):
    monkeypatch.setattr(parts, "_library_only_parts", lambda content=None: (
        parts.DetailPart("alpha", ("alpha",), ("alpha",), shared_images=False),))
    pane, _edits = _panel(qtbot)
    for name in ("hands", "alpha"):
        pane.open_fix_prompts(name)

    assert "fixes\\shared" in pane._fix_prompt_windows["hands"].training.train.toolTip()
    assert "shared" not in pane._fix_prompt_windows["alpha"].training.train.toolTip()


def test_a_trained_lora_is_put_on_its_fix(qtbot):
    pane, edits = _panel(qtbot)

    pane.use_fix_lora("hands", "fixes\\hands 2026-10-19 0130.safetensors")

    assert edits[-1].params["enhance_fix_prompts"]["hands"]["lora"] == (
        "fixes\\hands 2026-10-19 0130.safetensors")


def test_ok_on_a_fixs_prompts_keeps_them_and_cancel_keeps_nothing(qtbot):
    pane, edits = _panel(qtbot)
    pane._fix_prompt_buttons["hands"].click()
    window = pane._fix_prompt_windows["hands"]
    window.positive.boxes()[0].setPlainText("open palms")
    window.negative.boxes()[0].setPlainText("fists")

    window.accept()

    assert edits[-1].params["enhance_fix_prompts"] == {
        "hands": {"prompt": "open palms", "avoid": "fists", "lora": "", "strength": 1.0}}
    kept = len(edits)
    pane._fix_prompt_buttons["hands"].click()
    again = pane._fix_prompt_windows["hands"]
    assert (again.prompts()["prompt"], again.prompts()["avoid"]) == ("open palms", "fists")
    again.positive.boxes()[0].setPlainText("something else")
    again.reject()
    assert len(edits) == kept


@pytest.fixture
def clip_installed(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "COMFYUI_DIR", tmp_path / "ComfyUI")
    clip_reader(tmp_path / "ComfyUI")


@pytest.fixture
def boxed_fix(qtbot, clip_installed):
    pane, edits = _panel(qtbot)
    pane.show_settings(EnhanceSettings(params={
        **default_enhance_params(),
        "enhance_fix_prompts": {"hands": {"prompt": "open palms", "avoid": "fists"}}}))
    pane._fix_prompt_buttons["hands"].click()
    return pane._fix_prompt_windows["hands"], edits


def _cats(count: int) -> str:
    return " ".join(["cat"] * count)


def test_a_fixs_prompt_flows_into_boxes_of_whole_words_and_ok_keeps_them(qtbot, boxed_fix):
    window, edits = boxed_fix
    (box,) = window.positive.boxes()

    box.setPlainText(f"{_cats(74)} open palms")
    qtbot.waitUntil(lambda: len(window.positive.boxes()) == 2, timeout=5000)
    window.accept()

    assert edits[-1].params["enhance_fix_prompts"]["hands"]["prompt"] == (
        f"{_cats(74)}{BOX_BREAK}open palms")


def test_a_fixs_one_prompt_box_fills_its_column_as_its_field_always_has(boxed_fix):
    window, _edits = boxed_fix
    window.resize(700, 600)
    window.layout().activate()

    (box,) = window.positive.boxes()
    assert box.height() == window.positive.height() > 4 * box.fontMetrics().lineSpacing()


def test_a_fixs_trigger_word_clicked_in_goes_at_the_start_of_its_first_box_and_flows_on(
        qtbot, clip_installed, worded_fix):
    worded_fix.positive.boxes()[0].setPlainText(_cats(70))

    qtbot.mouseClick(worded_fix.prompt_warning, Qt.MouseButton.LeftButton)

    assert worded_fix.positive.value() == f"exmplstyle, {_cats(64)}{BOX_BREAK}{_cats(6)}"


def test_a_fixs_prompts_already_open_are_brought_forward_rather_than_opened_twice(qtbot):
    pane, _edits = _panel(qtbot)
    pane._fix_prompt_buttons["hands"].click()
    first = pane._fix_prompt_windows["hands"]

    pane._fix_prompt_buttons["hands"].click()

    assert pane._fix_prompt_windows["hands"] is first


def test_a_fix_windows_lora_dropdown_says_when_its_picked_lora_was_trained(
        qtbot, installed_models, titled_models):
    installed_models.add("loras", "fixes/hands 1.1.safetensors", arch="sdxl", lora=True,
                         metadata={"ss_training_finished_at": "1792851468.891"})
    pane, _edits = _panel(qtbot)
    pane._fix_prompt_buttons["hands"].click()
    window = pane._fix_prompt_windows["hands"]
    assert window.lora.toolTip() == ""

    window.lora.setCurrentIndex(window.lora.findData(r"fixes\hands 1.1.safetensors"))
    assert window.lora.toolTip() == f"Trained {datetime.fromtimestamp(1792851468.891).astimezone():%Y-%m-%d %H:%M}."

    window.lora.setCurrentIndex(window.lora.findData(NO_LORA))
    assert window.lora.toolTip() == ""


@pytest.fixture
def fix_in_two_versions(monkeypatch, tmp_path, installed_models, titled_models, worded_loras):
    _fix_images(monkeypatch, tmp_path, "one.jpg")
    titled_models({})
    worded_loras({"hands 1.0": ["zzold"], "hands 1.1": ["zznew"]})
    gone = installed_models.add("loras", "fixes/hands 1.0.safetensors", arch="sdxl", lora=True)
    installed_models.add("loras", "fixes/hands 1.1.safetensors", arch="sdxl", lora=True)
    return gone


_OLD_FIX_LORA, _NEW_FIX_LORA = r"fixes\hands 1.0.safetensors", r"fixes\hands 1.1.safetensors"


def _fix_window_on_the_old_version(qtbot, **seams):
    pane, _edits = _panel(qtbot, **seams)
    pane._keep_fix_prompts("hands", {"prompt": "zzold, a part", "avoid": "", "lora": _OLD_FIX_LORA,
                                     "strength": 1.0})
    pane._fix_prompt_buttons["hands"].click()
    return pane, pane._fix_prompt_windows["hands"]


def test_a_fixs_old_version_offers_the_trash_where_its_newest_offers_retrain(
        qtbot, fix_in_two_versions):
    _pane, window = _fix_window_on_the_old_version(qtbot)

    assert (window.training.train.isHidden(), window.training.trash.isHidden()) == (True, False)

    window.choose_lora(_NEW_FIX_LORA)

    assert (window.training.train.isHidden(), window.training.trash.isHidden()) == (False, True)


def test_a_fixs_trash_moves_the_window_and_what_is_kept_to_the_newest_version_and_its_word(
        qtbot, fix_in_two_versions):
    pane, window = _fix_window_on_the_old_version(
        qtbot, trash=lambda _lora, _parent: fix_in_two_versions.unlink() or True)

    window.training.trash.click()

    assert window.lora.currentData() == _NEW_FIX_LORA
    assert window.lora.findData(_OLD_FIX_LORA) < 0
    assert window.positive.value() == "zznew, a part"
    assert (pane._fix_prompts["hands"]["lora"], pane._fix_prompts["hands"]["prompt"]) == (
        _NEW_FIX_LORA, "zznew, a part")


def test_a_fix_trash_windows_refuses_stays_on_that_version(qtbot, fix_in_two_versions):
    _pane, window = _fix_window_on_the_old_version(qtbot, trash=lambda _lora, _parent: False)

    window.training.trash.click()

    assert window.lora.currentData() == _OLD_FIX_LORA


def test_a_fixs_window_opened_on_a_version_since_trashed_offers_to_switch(
        qtbot, fix_in_two_versions):
    fix_in_two_versions.unlink()
    _pane, window = _fix_window_on_the_old_version(qtbot)

    assert window.lora_warning.toolTip() == (
        "Not installed anymore, so nothing can be made with it. "
        "Click to use Hands fix 1.1 and its trigger word, zznew.")

    window.lora_warning.pressed.emit()

    assert window.lora.currentData() == _NEW_FIX_LORA
    assert window.positive.value() == "zznew, a part"


def test_a_second_load_clears_the_parts_the_first_one_ticked(qtbot):
    pane, _ = _panel(qtbot)
    pane.show_settings(EnhanceSettings(params={"enhance_detail_fixes": {"faces": 0.7}}))
    assert pane._fix_checks["faces"].isChecked()

    pane.show_settings(EnhanceSettings(params={}))

    assert not pane._fix_checks["faces"].isChecked(), (
        "a part the settings do not name is a part left alone: filling in only what is named would "
        "leave the last folder's fixes standing on a folder that asked for none")


def test_a_new_frame_at_the_same_settings_leaves_the_rows_facts_in_place(qtbot):
    versions = EnhanceVersions()
    qtbot.addWidget(versions)
    versions.show_versions(_items(_versions(1)), RunningEnhancement("running", None, "2x"))
    facts = versions._pending.findChildren(QLabel)

    versions.update_pending(RunningEnhancement("running", b"not a real png", "2x"))

    assert versions._pending.findChildren(QLabel) == facts, (
        "a run streams several frames a second, and each would otherwise rebuild the row under the cursor")


def test_the_original_does_not_drag(qtbot, tmp_path, version_drags):
    original = _VersionRow(_versions(1)[-1], 1, _an_image(tmp_path / "src.png"))
    qtbot.addWidget(original)

    qtbot.mousePress(original, Qt.MouseButton.LeftButton, pos=QPoint(2, 2))
    qtbot.mouseMove(original, QPoint(90, 90))

    assert version_drags == [], (
        "a drag onto the Enhance pane says do that again, and the original was made by no enhancement")

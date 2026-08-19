"""The Enhance subpanel and the version list beside it.

Two small widgets for the two halves of "enhancement is a layer": the subpanel
edits what a folder enhances at, and the version list shows what an image has
already received.
"""

import pytest
from PyQt6.QtCore import QPoint, Qt
from PyQt6.QtGui import QDropEvent

from origenerator.gallery import (
    MATCH_SOURCE_MODEL, EnhanceLevel, EnhanceSettings, default_enhance_params,
)
from origenerator.gui import enhance_versions as versions_module
from origenerator.gui.enhance_panel import EnhancePanel
from origenerator.gui.enhance_versions import (
    EnhanceVersions, _AddRow, _LevelRow, _PendingRow, enhance_level_mime,
    params_from_mime,
)
from origenerator.gui.toggle_switch import ToggleSwitch
from origenerator.workflows.detail_parts import DEFAULT_FIX_DENOISE, DETAIL_PARTS


_FOUND_DETECTORS = ("face_finder.pt", "hand_finder.pt")


def _panel(qtbot, detectors=_FOUND_DETECTORS):
    """A panel built against a stated set of installed detectors — the one thing
    on it that can be missing, and so the one thing a test must not read off
    whatever this machine happens to have in its ComfyUI."""
    import origenerator.workflows.detail_parts as parts

    edits = []
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(parts, "list_detector_files", lambda: list(detectors))
        panel = EnhancePanel(edits.append)
    qtbot.addWidget(panel)
    return panel, edits


def _levels(count, params=None):
    """``count`` enhancements over an original, newest first — the shape
    :func:`~origenerator.gallery.enhance.enhance_levels` produces. ``0`` is an
    image that has received none, which lists nothing at all (not even its own
    file: with no enhancement there is no version to compare)."""
    if not count:
        return []
    return [
        EnhanceLevel(i, f"Enhance {i}", {"filename": f"e{i}.png", "subfolder": "image"},
                     dict(params or {}))
        for i in range(count, 0, -1)
    ] + [EnhanceLevel(0, "Original", {"filename": "src.png", "subfolder": "image"})]


def _items(levels):
    """Pair each level with the file the list would draw it from — nothing on
    disk here, so the rows fall back to their labels."""
    return [(level, None) for level in levels]


# --- the subpanel ----------------------------------------------------------


def test_a_fresh_panel_reads_as_the_workflow_defaults_box_off(qtbot):
    panel, _ = _panel(qtbot)
    settings = panel.settings()
    assert settings.auto is False
    assert settings.params["enhance_scale"] == default_enhance_params()["enhance_scale"]
    assert settings.params["checkpoint"] == MATCH_SOURCE_MODEL


def test_auto_enhance_is_a_bare_switch_at_the_top_right(qtbot):
    # The panel's power, not one of its dials: a bare switch on the title row,
    # at the far end from the heading. What it does lives in its tooltip.
    panel, _ = _panel(qtbot)
    assert isinstance(panel._auto, ToggleSwitch)
    assert panel._auto.isCheckable()
    assert panel._auto.text() == ""
    assert panel._auto.toolTip()

    title_row = panel.layout().itemAt(0).layout()
    assert title_row.itemAt(0).widget().text() == "Enhance"      # the heading leads
    assert title_row.itemAt(title_row.count() - 1).widget() is panel._auto
    assert title_row.itemAt(1).spacerItem() is not None          # pushed to the right


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
    # It paints itself (a stylesheet cannot move a checkbox's indicator), so the
    # paint path is worth exercising in both positions.
    switch = ToggleSwitch("Auto")
    qtbot.addWidget(switch)
    switch.resize(switch.sizeHint())
    off = switch.grab().toImage()
    switch.setChecked(True)
    on = switch.grab().toImage()
    assert not off.isNull() and not on.isNull()
    assert off != on            # the knob and the track visibly moved


def test_loading_a_folders_settings_writes_nothing_back(qtbot):
    # Opening a folder fills the panel; that is not an edit, and must not
    # re-persist (which would stamp defaults over settings it failed to load).
    panel, edits = _panel(qtbot)
    panel.show_settings(EnhanceSettings(auto=True, params={"enhance_steps": 40}))
    assert edits == []
    assert panel.settings().auto is True
    assert panel.settings().params["enhance_steps"] == 40


def test_every_knob_reports_its_edit(qtbot):
    panel, edits = _panel(qtbot)
    panel._auto.setChecked(True)
    panel._scale.setValue(3.0)
    panel._steps.setValue(35)
    panel._denoise.setValue(0.4)

    assert len(edits) == 4          # each edit writes through on its own
    latest = edits[-1]
    assert latest.auto is True
    assert latest.params["enhance_scale"] == 3.0
    assert latest.params["enhance_steps"] == 35
    assert latest.params["enhance_denoise"] == 0.4


def test_every_fixable_part_gets_a_box_and_a_number_of_its_own(qtbot):
    # One of each per part the app can aim a detail pass at: the box says
    # whether that part is fixed, the number how hard — a mouth wants a harder
    # redraw than a face, and one shared number could never say so.
    panel, edits = _panel(qtbot)
    assert list(panel._fixes) == [part.name for part in DETAIL_PARTS]
    # Nothing ticked, so nothing pays for a pass it didn't ask for — while the
    # numbers already read as what a fix runs at.
    assert panel.settings().params["enhance_detail_fixes"] == {}
    assert panel._fixes["faces"].value() == DEFAULT_FIX_DENOISE

    panel._fix_checks["faces"].setChecked(True)
    panel._fix_checks["hands"].setChecked(True)
    panel._fixes["hands"].setValue(0.6)

    assert edits[-1].params["enhance_detail_fixes"] == {
        "faces": DEFAULT_FIX_DENOISE, "hands": 0.6}
    assert panel._fixes["faces"].toolTip() and panel._fix_checks["faces"].toolTip()


def test_a_fix_field_is_only_as_wide_as_the_number_it_holds(qtbot):
    # Seven parts share one line only if none of them is padded out: Qt's own
    # hint for a spin box is far wider than "0.00", and a field given a floor
    # and a share of the slack (as the three numbers above have) costs another
    # part its place on the line.
    panel, _ = _panel(qtbot)
    box = panel._fixes["faces"]
    digits = box.fontMetrics().horizontalAdvance("0.00")

    assert digits < box.minimumWidth() <= digits + 30   # its own chrome, no more
    assert box.minimumWidth() == box.maximumWidth()     # fixed, so a wide pane
    assert box.minimumWidth() < box.sizeHint().width()  # doesn't stretch it


def test_the_fixes_line_wraps_rather_than_widening_the_panel(qtbot):
    # The window tiles into a third of a monitor, so no row of fields may set
    # the floor for it — and a line too long to fit has to wrap, since a
    # clipped part is a setting that silently isn't there.
    panel, _ = _panel(qtbot)
    host = panel._fixes["faces"].parent().parent()
    flow = host.layout()
    pairs = [flow.itemAt(i).widget() for i in range(flow.count())]

    assert flow.heightForWidth(120) > flow.heightForWidth(4000)   # it wraps
    assert host.hasHeightForWidth()   # or the wrapped rows are cut off the bottom
    # Its floor is one part, not the whole line.
    assert host.minimumSizeHint().width() <= max(
        pair.sizeHint().width() for pair in pairs) + 8


def test_unticking_a_part_drops_its_fix_but_keeps_its_number(qtbot):
    # The tick is the on/off, so unticking must leave the settings — and leave
    # the number where it was, since the next tick means the same fix again.
    panel, edits = _panel(qtbot)
    panel._fix_checks["faces"].setChecked(True)
    panel._fixes["faces"].setValue(0.7)

    panel._fix_checks["faces"].setChecked(False)

    assert edits[-1].params["enhance_detail_fixes"] == {}
    assert panel._fixes["faces"].value() == 0.7
    # And off, the part reads as off rather than as a live setting.
    assert not panel._fixes["faces"].isEnabled()


def test_an_unticked_parts_name_and_number_grey_out(qtbot):
    # Which parts are on has to be readable down the line at a glance, not
    # worked out box by box.
    panel, _ = _panel(qtbot)
    label = panel._label_for(panel._fixes["faces"])

    assert not label.isEnabled() and not panel._fixes["faces"].isEnabled()

    panel._fix_checks["faces"].setChecked(True)

    assert label.isEnabled() and panel._fixes["faces"].isEnabled()


def test_a_part_with_no_detector_installed_cannot_be_ticked(qtbot):
    # The settings here that can be unavailable rather than merely unset: the
    # model that finds a part is a separate install, and a run naming one
    # ComfyUI hasn't got is rejected on submit. Better a box that says why than
    # one that quietly fails.
    panel, _ = _panel(qtbot, detectors=("face_finder.pt",))
    assert panel._fix_checks["faces"].isEnabled()
    assert not panel._fix_checks["hands"].isEnabled()
    # The whole setup, in the one place someone reads carefully: the node pack
    # that runs the detectors, the folder the models go in, and what the file
    # this part needs is called.
    tooltip = panel._fix_checks["hands"].toolTip()
    assert "models/ultralytics/bbox" in tooltip
    assert "Impact Subpack" in tooltip
    assert "hand" in tooltip
    assert panel._label_for(panel._fixes["hands"]).toolTip() == tooltip


def test_a_detector_by_another_name_does_not_count_as_installed(qtbot):
    # Some other detector sitting in that folder would leave every box tickable
    # and every pass finding nothing. Unavailable says which file to add.
    panel, _ = _panel(qtbot, detectors=("cat_finder.pt",))
    assert not any(box.isEnabled() for box in panel._fix_checks.values())


def _mean_ink(widget) -> float:
    """How bright the widget draws over the app's own background, averaged over
    every pixel — the one thing a "does it actually look disabled?" test can
    measure without fonts.

    Rendered onto a filled pixmap rather than grabbed: a bare ``grab`` leaves
    whatever the widget doesn't paint uninitialized, and a switch that dims by
    going translucent then measures as whatever happened to be behind it.
    """
    from PyQt6.QtGui import QPixmap
    from PyQt6.QtWidgets import QWidget
    from shared_ui.colors import BG_PRIMARY

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
    # setEnabled alone changed nothing here: the app's sheet colors every label,
    # picker and spin box outright and names no disabled state, so a panel that
    # could not apply went on reading exactly as live as one that could.
    panel, _ = _panel(qtbot)
    panel.show_settings(EnhanceSettings(auto=True, params={}))
    panel.resize(360, 150)
    panel.show()
    qtbot.waitExposed(panel)
    live = _mean_ink(panel)

    panel.set_applicable(False, "no video enhancer")

    assert not panel.isEnabled()
    assert panel.toolTip() == "no video enhancer"
    assert _mean_ink(panel) < live      # visibly dimmer, not merely inert

    panel.set_applicable(True)
    assert panel.isEnabled() and panel.toolTip() == ""


def test_coming_back_on_leaves_the_detail_pass_dimmed_without_a_detector(qtbot):
    # Switching the panel off and on again must not hand back a knob that was
    # grayed in its own right: the part still has no model to find it.
    panel, _ = _panel(qtbot, detectors=())
    panel.set_applicable(False, "nope")
    panel.set_applicable(True)
    assert panel.isEnabled() and not panel._fix_checks["faces"].isEnabled()


def test_a_disabled_toggle_switch_dims(qtbot):
    # It paints itself, so nothing else would have dimmed it — and a switch that
    # still looks on inside a panel gone dark is the one thing that says the
    # panel is still live.
    on = ToggleSwitch()
    qtbot.addWidget(on)
    on.setChecked(True)
    on.resize(40, 22)
    off = ToggleSwitch()
    qtbot.addWidget(off)
    off.setChecked(True)
    off.resize(40, 22)
    off.setEnabled(False)

    assert _mean_ink(off) < _mean_ink(on)


def test_a_model_no_longer_installed_is_still_shown(qtbot):
    # A folder configured against a checkpoint since removed must come back
    # reading as that checkpoint, not silently snap to whatever sorts first.
    panel, _ = _panel(qtbot)
    panel.show_settings(EnhanceSettings(params={"checkpoint": "retired_v1.safetensors"}))
    assert panel.settings().params["checkpoint"] == "retired_v1.safetensors"


def test_settings_survive_a_load_and_read_back(qtbot):
    panel, _ = _panel(qtbot)
    original = EnhanceSettings(auto=True, params=dict(default_enhance_params(),
                                                      enhance_scale=2.5,
                                                      enhance_steps=31,
                                                      enhance_denoise=0.22))
    panel.show_settings(original)
    assert panel.settings() == original


# --- the version list ------------------------------------------------------


def _rows(widget):
    return widget._host.findChildren(_LevelRow)


def _labels(widget):
    """Each row's title — the level it names."""
    return [row._title.text() for row in _rows(widget)]


def _facts(row):
    """Every label on one row, its em-dash "file is gone" placeholder dropped."""
    from PyQt6.QtWidgets import QLabel
    return " / ".join(lbl.text().replace("​", "")
                      for lbl in row.findChildren(QLabel)
                      if lbl.text() and lbl.text() != "—")


def test_an_unenhanced_image_shows_no_version_strip(qtbot):
    versions = EnhanceVersions()
    qtbot.addWidget(versions)
    versions.show_levels(_items(_levels(0)))
    assert versions.isHidden()      # no enhancement, nothing to say


def test_a_lone_enhancement_is_still_worth_showing(qtbot):
    # An image the inline tail finished kept no original, so it has exactly one
    # level. The badge says it was enhanced; this is where you see how.
    versions = EnhanceVersions()
    qtbot.addWidget(versions)
    versions.show_levels(_items([
        EnhanceLevel(1, "Enhance 1", {"filename": "img.png"},
                     {"enhance_scale": 2.0, "enhance_steps": 20}),
    ]))
    assert not versions.isHidden()
    assert len(_rows(versions)) == 1


def test_levels_are_shown_newest_first(qtbot):
    versions = EnhanceVersions()
    qtbot.addWidget(versions)
    versions.show_levels(_items(_levels(2)))
    assert not versions.isHidden()
    assert _labels(versions) == ["Enhance 2", "Enhance 1", "Original"]


def test_clicking_a_level_reports_its_position(qtbot):
    versions = EnhanceVersions()
    qtbot.addWidget(versions)
    versions.show_levels(_items(_levels(2)))
    picked = []
    versions.level_selected.connect(picked.append)

    row = _rows(versions)[2]      # the original
    qtbot.mousePress(row, Qt.MouseButton.LeftButton)
    qtbot.mouseRelease(row, Qt.MouseButton.LeftButton)

    assert picked == [2]
    assert versions.selected_positions() == [2]   # and it is the picked one


def test_each_level_carries_its_own_file_and_created_rows(qtbot):
    # The file information is per enhancement: it belongs with the level that
    # made the file, alongside the settings that made it.
    versions = EnhanceVersions()
    qtbot.addWidget(versions)
    versions.show_levels(_items(_levels(1, {"enhance_scale": 2.0})),
                         created_fallback="2026-08-01")

    facts = _facts(_rows(versions)[0])
    assert "Enhancement" in facts and "2x" in facts
    assert "File" in facts and "image/e1.png" in facts
    # The file isn't on disk here, so its own write time can't be read — the
    # row's timestamp is the closest true answer left.
    assert "Created" in facts and "2026-08-01" in facts


def test_a_file_row_can_be_copied_and_revealed(qtbot):
    from PyQt6.QtWidgets import QPushButton

    versions = EnhanceVersions()
    qtbot.addWidget(versions)
    versions.show_levels(_items(_levels(1)))

    names = {b.objectName() for b in _rows(versions)[0].findChildren(QPushButton)}
    assert "copyButton" in names and "revealButton" in names


def test_a_levels_settings_caption_its_row(qtbot):
    versions = EnhanceVersions()
    qtbot.addWidget(versions)
    versions.show_levels(_items(_levels(1, {"enhance_scale": 2.0, "enhance_steps": 20})))
    facts = _facts(_rows(versions)[0])
    assert "2x" in facts
    assert "20 steps" in facts


def test_rebuilding_for_another_image_drops_the_old_rows(qtbot):
    # Switching selection must not stack one image's levels under another's.
    versions = EnhanceVersions()
    qtbot.addWidget(versions)
    versions.show_levels(_items(_levels(2)))
    versions.show_levels(_items(_levels(1)))
    assert _labels(versions) == ["Enhance 1", "Original"]


# --- picking levels and binning them ---------------------------------------


def _click(qtbot, row, modifier=Qt.KeyboardModifier.NoModifier):
    qtbot.mousePress(row, Qt.MouseButton.LeftButton, modifier)
    qtbot.mouseRelease(row, Qt.MouseButton.LeftButton, modifier)


def test_clicking_anywhere_on_a_row_picks_it(qtbot):
    # A row is one thing to click. Its picture and its lines of text cover
    # nearly all of it, and a child widget takes the press by default — which
    # left only the margins around them live.
    from PyQt6.QtWidgets import QLabel

    versions = EnhanceVersions()
    qtbot.addWidget(versions)
    versions.show_levels(_items(_levels(1)), created_fallback="2026-08-01")
    row = _rows(versions)[0]

    targets = [row._picture, row._title]
    targets += [lbl for lbl in row.findChildren(QLabel) if lbl.text() == "File"]
    for target in targets:
        assert row.childAt(target.mapTo(row, QPoint(3, 3))) is None, target.text()


def test_the_buttons_on_a_row_still_take_their_own_clicks(qtbot):
    # The pass-through must stop at the copy and Show-in-Explorer buttons: Qt's
    # hit test skips a container marked transparent along with everything inside
    # it, so these are laid into the row's grid rather than into one.
    from PyQt6.QtWidgets import QPushButton

    versions = EnhanceVersions()
    qtbot.addWidget(versions)
    versions.show_levels(_items(_levels(1)))
    row = _rows(versions)[0]

    buttons = row.findChildren(QPushButton)
    assert {b.objectName() for b in buttons} == {"copyButton", "revealButton"}
    for button in buttons:
        assert row.childAt(button.mapTo(row, QPoint(3, 3))) is button


def test_a_rows_text_offers_no_copy_or_select_all_menu(qtbot):
    # The value labels come from the metadata block, where they are selectable
    # text — and Qt gives selectable text its own Copy / Select All menu. Over a
    # version that menu means nothing (the row has a Copy button for the one
    # value worth copying) and it is in the way of the row's own Delete.
    from PyQt6.QtWidgets import QLabel

    versions = EnhanceVersions()
    qtbot.addWidget(versions)
    versions.show_levels(_items(_levels(1)), created_fallback="2026-08-01")
    row = _rows(versions)[0]

    for label in row.findChildren(QLabel):
        assert label.contextMenuPolicy() == Qt.ContextMenuPolicy.NoContextMenu
    assert row.contextMenuPolicy() == Qt.ContextMenuPolicy.CustomContextMenu


def test_a_plain_click_picks_one_level_at_a_time(qtbot):
    versions = EnhanceVersions()
    qtbot.addWidget(versions)
    versions.show_levels(_items(_levels(2)))

    _click(qtbot, _rows(versions)[0])
    _click(qtbot, _rows(versions)[2])

    assert versions.selected_positions() == [2]


def test_ctrl_click_adds_to_the_picking(qtbot):
    # The gesture is "these ones", aimed at the Delete that follows — so it
    # doesn't swap the preview under each click either.
    versions = EnhanceVersions()
    qtbot.addWidget(versions)
    versions.show_levels(_items(_levels(2)))
    shown = []
    versions.level_selected.connect(shown.append)

    _click(qtbot, _rows(versions)[0])
    _click(qtbot, _rows(versions)[1], Qt.KeyboardModifier.ControlModifier)

    assert versions.selected_positions() == [0, 1]
    assert shown == [0]   # only the plain click moved the preview


def test_delete_and_backspace_bin_the_picked_levels(qtbot):
    # Sent to the row, not to the list: a click leaves the focus on the row it
    # picked (the rows take click focus), so the key has to reach the list from
    # there rather than only when the list itself happens to hold the focus.
    for key in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace):
        versions = EnhanceVersions()
        qtbot.addWidget(versions)
        versions.show_levels(_items(_levels(2)))
        asked = []
        versions.delete_requested.connect(asked.append)

        row = _rows(versions)[0]
        _click(qtbot, row)
        assert row.focusPolicy() == Qt.FocusPolicy.ClickFocus
        qtbot.keyClick(row, key)

        assert asked == [[0]]


def test_deleting_the_only_version_is_refused(qtbot):
    # An image with no file left is a deleted generation, and that is the
    # gallery's own delete, reached from the thumbnail.
    versions = EnhanceVersions()
    qtbot.addWidget(versions)
    versions.show_levels(_items(_levels(1)))
    asked = []
    versions.delete_requested.connect(asked.append)

    for row in _rows(versions):
        row.set_selected(True)
    qtbot.keyClick(versions, Qt.Key.Key_Delete)

    assert asked == []


def test_the_context_menu_deletes_what_it_opened_over(qtbot, monkeypatch):
    # A right-click on an unpicked row picks it first, so the menu always acts
    # on what it appeared over.
    from PyQt6.QtWidgets import QMenu

    versions = EnhanceVersions()
    qtbot.addWidget(versions)
    versions.show_levels(_items(_levels(2)))
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


def test_the_menus_delete_grays_out_when_it_would_empty_the_image(qtbot, monkeypatch):
    from PyQt6.QtWidgets import QMenu

    versions = EnhanceVersions()
    qtbot.addWidget(versions)
    versions.show_levels(_items(_levels(1)))
    asked = []
    versions.delete_requested.connect(asked.append)
    seen = {}

    def _exec(self, _pos):
        action = self.actions()[0]
        seen["text"] = action.text()
        seen["enabled"] = action.isEnabled()
        return action

    monkeypatch.setattr(QMenu, "exec", _exec)

    for row in _rows(versions):
        row.set_selected(True)
    versions._on_row_menu(0, QPoint(0, 0))

    assert seen["enabled"] is False
    assert "only version" in seen["text"]   # grayed with the reason on it
    assert asked == []


# --- dragging a level onto the panel to reuse its settings -----------------


# --- the "+ Enhance" card ---------------------------------------------------


def test_the_add_card_leads_the_strip_and_reports_its_press(qtbot):
    # Leftmost, because that is where a new version arrives: the strip runs
    # newest first.
    versions = EnhanceVersions()
    qtbot.addWidget(versions)
    versions.show_levels(_items(_levels(1)), add=("2x · 20 steps", None))
    tiles = versions._host.findChildren((_LevelRow, _AddRow))
    assert isinstance(tiles[0], _AddRow)

    pressed = []
    versions.enhance_requested.connect(lambda: pressed.append(True))
    qtbot.mouseRelease(tiles[0], Qt.MouseButton.LeftButton)
    assert pressed == [True]


def test_a_running_enhance_takes_the_add_cards_slot_rather_than_sitting_beside_it(qtbot):
    # The card becomes the thing it asked for, which is what the press looks
    # like from the other side.
    versions = EnhanceVersions()
    qtbot.addWidget(versions)
    versions.show_levels(_items(_levels(1)), pending=("running", None, "2x"),
                         add=("2x", None))
    tiles = versions._host.findChildren((_PendingRow, _AddRow, _LevelRow))
    assert isinstance(tiles[0], _PendingRow)
    assert not versions._host.findChildren(_AddRow)


def test_an_image_with_nothing_yet_still_gets_the_card(qtbot):
    versions = EnhanceVersions()
    qtbot.addWidget(versions)
    versions.show_levels([], add=("2x", None))
    assert not versions.isHidden()
    assert versions._host.findChildren(_AddRow)


def test_the_card_dims_when_it_would_only_duplicate_a_level(qtbot):
    versions = EnhanceVersions()
    qtbot.addWidget(versions)
    versions.show_levels(_items(_levels(1)), add=("2x · 20 steps", 0))
    (card,) = versions._host.findChildren(_AddRow)

    pressed = []
    versions.enhance_requested.connect(lambda: pressed.append(True))
    qtbot.mouseRelease(card, Qt.MouseButton.LeftButton)
    assert pressed == []                       # it makes nothing new, so it does nothing
    assert "already has a version" in card.toolTip()


def test_hovering_the_dimmed_card_lights_the_level_it_would_duplicate(qtbot):
    versions = EnhanceVersions()
    qtbot.addWidget(versions)
    versions.show_levels(_items(_levels(2)), add=("2x", 1))
    duplicate = versions._rows[1]
    assert duplicate._picture.styleSheet() == ""

    versions._highlight_level(1, True)
    assert "border" in duplicate._picture.styleSheet()
    versions._highlight_level(1, False)
    assert duplicate._picture.styleSheet() == ""


def test_a_level_carries_its_settings_as_a_drag_payload():
    params = {"enhance_scale": 3.0, "enhance_steps": 40, "enhance_denoise": 0.35}
    assert params_from_mime(enhance_level_mime(params)) == params


def test_a_foreign_drag_carries_nothing_this_panel_wants():
    from PyQt6.QtCore import QMimeData
    mime = QMimeData()
    mime.setText("just some text")
    assert params_from_mime(mime) is None


def test_the_dragged_version_trails_the_cursor(qtbot, tmp_path, monkeypatch):
    # The same gesture as dragging a gallery thumbnail onto Combine: the picture
    # comes along under the cursor, so what is being dragged is never in doubt.
    from PIL import Image

    image = tmp_path / "e1.png"
    Image.new("RGB", (16, 16), (200, 80, 40)).save(image)

    dragged = {}

    class _RecordingDrag:
        def __init__(self, source):
            dragged["source"] = source

        def setMimeData(self, mime):
            dragged["mime"] = mime

        def setPixmap(self, pixmap):
            dragged["pixmap"] = pixmap

        def exec(self, _action):
            return None

    monkeypatch.setattr(versions_module, "QDrag", _RecordingDrag)

    (level,) = _levels(1, {"enhance_scale": 2.0})[:1]
    tile = _LevelRow(level, 0, image)
    qtbot.addWidget(tile)
    qtbot.mousePress(tile, Qt.MouseButton.LeftButton, pos=QPoint(2, 2))
    qtbot.mouseMove(tile, QPoint(90, 90))

    assert "pixmap" in dragged and not dragged["pixmap"].isNull()
    assert params_from_mime(dragged["mime"]) == {"enhance_scale": 2.0}


def test_a_big_versions_picture_drags_at_the_shared_size(qtbot, tmp_path, monkeypatch):
    # An enhancement is an upscale, so the file behind a version can be huge; the
    # picture under the cursor is the same thumbnail every other drag trails.
    from PIL import Image

    from origenerator.gui.drag_thumbnail import THUMBNAIL_BOX

    image = tmp_path / "big.png"
    Image.new("RGB", (1024, 768), (60, 90, 200)).save(image)

    dragged = {}

    class _RecordingDrag:
        def __init__(self, source):
            pass

        def setMimeData(self, mime):
            pass

        def setPixmap(self, pixmap):
            dragged["pixmap"] = pixmap

        def exec(self, _action):
            return None

    monkeypatch.setattr(versions_module, "QDrag", _RecordingDrag)

    tile = _LevelRow(_levels(1, {"enhance_scale": 2.0})[0], 0, image)
    qtbot.addWidget(tile)
    qtbot.mousePress(tile, Qt.MouseButton.LeftButton, pos=QPoint(2, 2))
    qtbot.mouseMove(tile, QPoint(90, 90))

    picture = dragged["pixmap"]
    assert max(picture.width(), picture.height()) == THUMBNAIL_BOX


def test_a_missing_file_drags_without_a_picture(qtbot, monkeypatch):
    # A level whose file is gone still carries its settings; there is simply no
    # image to trail, and that must not stop the drag.
    class _RecordingDrag:
        def __init__(self, source):
            pass

        def setMimeData(self, mime):
            pass

        def setPixmap(self, pixmap):
            raise AssertionError("nothing to show, so nothing should be set")

        def exec(self, _action):
            return None

    monkeypatch.setattr(versions_module, "QDrag", _RecordingDrag)

    tile = _LevelRow(_levels(1, {"enhance_scale": 2.0})[0], 0, None)
    qtbot.addWidget(tile)
    qtbot.mousePress(tile, Qt.MouseButton.LeftButton, pos=QPoint(2, 2))
    qtbot.mouseMove(tile, QPoint(90, 90))


# --- the enhancement being generated right now -----------------------------


def test_a_running_enhance_leads_the_strip(qtbot):
    versions = EnhanceVersions()
    qtbot.addWidget(versions)
    versions.show_levels(_items(_levels(1)), ("running", None, "2x"))
    tiles = versions._host.findChildren((_PendingRow, _LevelRow))
    assert isinstance(tiles[0], _PendingRow)   # newest first, and it's becoming that


def test_a_first_enhance_brings_the_strip_out_on_its_own(qtbot):
    # An image with only its original has no levels to choose between — but one
    # being made for it is worth showing, so the strip appears for that alone.
    versions = EnhanceVersions()
    qtbot.addWidget(versions)
    versions.show_levels(_items(_levels(0)), ("queued", None, "2x"))
    assert not versions.isHidden()


def test_the_live_tile_names_the_settings_it_is_running_at(qtbot):
    # "Enhancing" alone says nothing you didn't already know; the numbers are
    # the only thing worth reading off a tile that has no picture yet.
    from PyQt6.QtWidgets import QLabel

    versions = EnhanceVersions()
    qtbot.addWidget(versions)
    versions.show_levels(_items(_levels(1)),
                         ("queued", None, "3x · 40 steps · 0.35 denoise"))
    texts = [lbl.text().replace("​", "")
             for lbl in versions._pending.findChildren(QLabel)]
    assert "Queued…" in texts
    assert any("40 steps" in t and "0.35 denoise" in t for t in texts)
    assert "3x · 40 steps · 0.35 denoise" in versions._pending.toolTip()


def test_a_new_frame_updates_the_tile_without_a_rebuild(qtbot):
    versions = EnhanceVersions()
    qtbot.addWidget(versions)
    versions.show_levels(_items(_levels(1)), ("running", None, "2x"))
    tile = versions._pending

    assert versions.update_pending(("running", b"not a real png", "2x")) is True
    assert versions._pending is tile          # the same widget, fed in place

    # A run starting or ending changes the strip's shape, which only a rebuild
    # can do — the caller is told so rather than left with a stale strip.
    assert versions.update_pending(None) is False


def test_dropping_a_level_absorbs_its_settings(qtbot):
    panel, edits = _panel(qtbot)
    panel._auto.setChecked(True)
    edits.clear()
    # Held in a local: a QMimeData freed mid-event takes the handler with it.
    mime = enhance_level_mime({"enhance_scale": 3.0, "enhance_steps": 40,
                               "enhance_denoise": 0.35})
    event = QDropEvent(QPoint(5, 5).toPointF(), Qt.DropAction.CopyAction, mime,
                       Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)

    panel.dropEvent(event)

    settings = panel.settings()
    assert settings.params["enhance_scale"] == 3.0
    assert settings.params["enhance_steps"] == 40
    assert settings.params["enhance_denoise"] == 0.35
    # The drop says what to enhance at, not whether to keep enhancing.
    assert settings.auto is True
    assert edits and edits[-1] == settings


def test_the_strip_folds_away_like_the_form_sections_above_it(qtbot):
    # The pane is one column of collapsible groups; a heading that cannot fold
    # reads as the one thing you are not allowed to put away.
    from origenerator.gui.collapsible_section import CollapsibleSection

    versions = EnhanceVersions()
    qtbot.addWidget(versions)
    versions.show_levels(_items(_levels(1)), add=("2x", None))

    (section,) = versions.findChildren(CollapsibleSection)
    assert "Enhancement levels" in section._header.text()
    assert not versions.is_collapsed()

    versions.set_collapsed(True)
    assert versions.is_collapsed()
    assert section.content().isHidden()   # the tiles fold away with it


def test_folding_survives_a_rebuild_for_another_image(qtbot):
    versions = EnhanceVersions()
    qtbot.addWidget(versions)
    versions.set_collapsed(True)
    versions.show_levels(_items(_levels(2)), add=("2x", None))
    assert versions.is_collapsed()


def test_a_narrow_row_puts_its_facts_under_the_picture(qtbot):
    """The widest thing in the tab wraps rather than set the pane's floor.

    A picture beside a file's facts and buttons wants some 450px side by side,
    which is wider than a tiling-narrow info pane can be — so the pane would have
    had to choose between refusing to fit a monitor third and scrolling its
    settings sideways. Stacked, the row asks for the wider of the two rather than
    their sum, and neither has to give.
    """
    from PyQt6.QtWidgets import QApplication, QVBoxLayout, QWidget

    (level,) = _levels(1)[:1]
    row = _LevelRow(level, 0, None)
    host = QWidget()
    box = QVBoxLayout(host)
    box.setContentsMargins(0, 0, 0, 0)
    box.addWidget(row)
    qtbot.addWidget(host)
    host.show()

    side_by_side = row._picture.sizeHint().width() + row._facts.minimumSize().width()
    assert row.minimumSizeHint().width() < side_by_side

    host.resize(side_by_side + 60, 400)          # room for both
    QApplication.processEvents()
    assert row._title.x() > row._picture.x() + row._picture.width()
    assert row._title.y() < row._picture.y() + row._picture.height()

    host.resize(row.minimumSizeHint().width(), 400)   # room for one
    QApplication.processEvents()
    assert row._title.y() >= row._picture.y() + row._picture.height()

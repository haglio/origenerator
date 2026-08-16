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
    EnhanceVersions, _AddTile, _LevelTile, _PendingTile, enhance_level_mime,
    params_from_mime,
)
from origenerator.gui.toggle_switch import ToggleSwitch
from origenerator.workflows import WORKFLOW_REGISTRY


def _wanted_detectors() -> tuple[str, str]:
    """The face and hand models the detail pass looks for, read off the workflow
    rather than retyped — the panel offers the pass only when one is installed,
    so a test that named its own files would be measuring the wrong thing."""
    defaults = WORKFLOW_REGISTRY["image_enhance"].default_params()
    return (defaults["enhance_face_detector"], defaults["enhance_hand_detector"])


def _panel(qtbot, detectors=None):
    """A panel built against a stated set of installed face/hand detectors —
    the one thing on it that can be missing, and so the one thing a test must
    not read off whatever this machine happens to have in its ComfyUI."""
    import origenerator.workflows.image_enhance as enhancer

    if detectors is None:
        detectors = _wanted_detectors()
    edits = []
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(enhancer, "list_detector_files", lambda: list(detectors))
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
    """Pair each level with the file the strip would draw it from — nothing on
    disk here, so the tiles fall back to their labels."""
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


def test_the_detail_pass_is_a_check_and_a_denoise_of_its_own(qtbot):
    # The pass is bolder than the enhance around it precisely because it only
    # touches the regions it found, so it carries its own denoise rather than
    # sharing the one above it.
    panel, edits = _panel(qtbot)
    assert panel._detail.isEnabled()
    assert panel.settings().params["enhance_detail_fix"] is False

    panel._detail.setChecked(True)
    panel._detail_denoise.setValue(0.5)

    assert edits[-1].params["enhance_detail_fix"] is True
    assert edits[-1].params["enhance_detail_denoise"] == 0.5
    assert panel._detail.toolTip() and panel._detail_denoise.toolTip()


def test_the_detail_pass_dims_itself_when_no_detector_is_installed(qtbot):
    # The one setting here that can be unavailable: the models that find the
    # faces and hands are a separate install, and a run without one is rejected
    # on submit. Better a control that says why than a tick that quietly fails.
    panel, _ = _panel(qtbot, detectors=())
    assert not panel._detail.isEnabled()
    assert not panel._detail_denoise.isEnabled()
    # The whole setup, in the one place someone reads carefully: the node pack
    # that runs the detectors as well as the folder the models go in.
    assert "models/ultralytics/bbox" in panel._detail.toolTip()
    assert "Impact Subpack" in panel._detail.toolTip()


def test_a_detector_by_another_name_does_not_count_as_installed(qtbot):
    # The pass names the two models it looks for, so some other detector sitting
    # in that folder would leave the box tickable and the pass finding nothing.
    # Dimmed names the file to add; enabled-but-inert says nothing at all.
    panel, _ = _panel(qtbot, detectors=("cat_finder.pt",))
    assert not panel._detail.isEnabled()
    assert all(name in panel._detail.toolTip() for name in _wanted_detectors())


def test_one_of_the_two_detectors_is_enough_to_offer_the_pass(qtbot):
    # Faces and hands are found by different models, and having only one is an
    # ordinary install — the half that can run still should.
    panel, _ = _panel(qtbot, detectors=_wanted_detectors()[:1])
    assert panel._detail.isEnabled()
    assert panel._detail_denoise.isEnabled()


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


# --- the version strip -----------------------------------------------------


def _tiles(widget):
    return widget._host.findChildren(_LevelTile)


def _labels(widget):
    """Each tile's text, its em-dash "file is gone" placeholder dropped."""
    from PyQt6.QtWidgets import QLabel
    return [
        " / ".join(lbl.text() for lbl in tile.findChildren(QLabel)
                   if lbl.text() and lbl.text() != "—")
        for tile in _tiles(widget)
    ]


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
    assert len(_tiles(versions)) == 1


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

    tile = _tiles(versions)[2]      # the original
    qtbot.mousePress(tile, Qt.MouseButton.LeftButton)
    qtbot.mouseRelease(tile, Qt.MouseButton.LeftButton)

    assert picked == [2]


def test_a_levels_settings_caption_its_tile(qtbot):
    versions = EnhanceVersions()
    qtbot.addWidget(versions)
    versions.show_levels(_items(_levels(1, {"enhance_scale": 2.0, "enhance_steps": 20})))
    assert "2x" in _labels(versions)[0]
    assert "20 steps" in _labels(versions)[0]


def test_rebuilding_for_another_image_drops_the_old_tiles(qtbot):
    # Switching selection must not stack one image's levels under another's.
    versions = EnhanceVersions()
    qtbot.addWidget(versions)
    versions.show_levels(_items(_levels(2)))
    versions.show_levels(_items(_levels(1)))
    assert _labels(versions) == ["Enhance 1", "Original"]


# --- dragging a level onto the panel to reuse its settings -----------------


# --- the "+ Enhance" card ---------------------------------------------------


def test_the_add_card_leads_the_strip_and_reports_its_press(qtbot):
    # Leftmost, because that is where a new version arrives: the strip runs
    # newest first.
    versions = EnhanceVersions()
    qtbot.addWidget(versions)
    versions.show_levels(_items(_levels(1)), add=("2x · 20 steps", None))
    tiles = versions._host.findChildren((_LevelTile, _AddTile))
    assert isinstance(tiles[0], _AddTile)

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
    tiles = versions._host.findChildren((_PendingTile, _AddTile, _LevelTile))
    assert isinstance(tiles[0], _PendingTile)
    assert not versions._host.findChildren(_AddTile)


def test_an_image_with_nothing_yet_still_gets_the_card(qtbot):
    versions = EnhanceVersions()
    qtbot.addWidget(versions)
    versions.show_levels([], add=("2x", None))
    assert not versions.isHidden()
    assert versions._host.findChildren(_AddTile)


def test_the_card_dims_when_it_would_only_duplicate_a_level(qtbot):
    versions = EnhanceVersions()
    qtbot.addWidget(versions)
    versions.show_levels(_items(_levels(1)), add=("2x · 20 steps", 0))
    (card,) = versions._host.findChildren(_AddTile)

    pressed = []
    versions.enhance_requested.connect(lambda: pressed.append(True))
    qtbot.mouseRelease(card, Qt.MouseButton.LeftButton)
    assert pressed == []                       # it makes nothing new, so it does nothing
    assert "already has a version" in card.toolTip()


def test_hovering_the_dimmed_card_lights_the_level_it_would_duplicate(qtbot):
    versions = EnhanceVersions()
    qtbot.addWidget(versions)
    versions.show_levels(_items(_levels(2)), add=("2x", 1))
    duplicate = versions._tiles[1]
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
    tile = _LevelTile(level, 0, image)
    qtbot.addWidget(tile)
    qtbot.mousePress(tile, Qt.MouseButton.LeftButton, pos=QPoint(2, 2))
    qtbot.mouseMove(tile, QPoint(90, 90))

    assert "pixmap" in dragged and not dragged["pixmap"].isNull()
    assert params_from_mime(dragged["mime"]) == {"enhance_scale": 2.0}


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

    tile = _LevelTile(_levels(1, {"enhance_scale": 2.0})[0], 0, None)
    qtbot.addWidget(tile)
    qtbot.mousePress(tile, Qt.MouseButton.LeftButton, pos=QPoint(2, 2))
    qtbot.mouseMove(tile, QPoint(90, 90))


# --- the enhancement being generated right now -----------------------------


def test_a_running_enhance_leads_the_strip(qtbot):
    versions = EnhanceVersions()
    qtbot.addWidget(versions)
    versions.show_levels(_items(_levels(1)), ("running", None, "2x"))
    tiles = versions._host.findChildren((_PendingTile, _LevelTile))
    assert isinstance(tiles[0], _PendingTile)   # newest first, and it's becoming that


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
    texts = [lbl.text() for lbl in versions._pending.findChildren(QLabel)]
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

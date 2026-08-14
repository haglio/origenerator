"""The Enhance subpanel and the version list beside it.

Two small widgets for the two halves of "enhancement is a layer": the subpanel
edits what a folder enhances at, and the version list shows what an image has
already received.
"""

from PyQt6.QtCore import QPoint, Qt
from PyQt6.QtGui import QDropEvent

from origenerator.gallery import (
    MATCH_SOURCE_MODEL, EnhanceLevel, EnhanceSettings, default_enhance_params,
)
from origenerator.gui.enhance_panel import EnhancePanel
from origenerator.gui.enhance_versions import (
    EnhanceVersions, _LevelTile, enhance_level_mime, params_from_mime,
)


def _panel(qtbot):
    edits = []
    panel = EnhancePanel(edits.append)
    qtbot.addWidget(panel)
    return panel, edits


def _levels(count, params=None):
    """``count`` enhancements over an original, newest first — the shape
    :func:`~origenerator.gallery.enhance.enhance_levels` produces."""
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
    assert versions.isHidden()      # nothing to choose between


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


def test_a_level_carries_its_settings_as_a_drag_payload():
    params = {"enhance_scale": 3.0, "enhance_steps": 40, "enhance_denoise": 0.35}
    assert params_from_mime(enhance_level_mime(params)) == params


def test_a_foreign_drag_carries_nothing_this_panel_wants():
    from PyQt6.QtCore import QMimeData
    mime = QMimeData()
    mime.setText("just some text")
    assert params_from_mime(mime) is None


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

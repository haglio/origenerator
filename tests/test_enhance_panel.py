"""The Enhance subpanel and the version list beside it.

Two small widgets for the two halves of "enhancement is a layer": the subpanel
edits what a folder enhances at, and the version list shows what an image has
already received.
"""

from PyQt6.QtWidgets import QPushButton

from origenerator.gallery import (
    MATCH_SOURCE_MODEL, EnhanceLevel, EnhanceSettings, default_enhance_params,
)
from origenerator.gui.enhance_panel import EnhancePanel
from origenerator.gui.enhance_versions import EnhanceVersions


def _panel(qtbot):
    edits = []
    panel = EnhancePanel(edits.append)
    qtbot.addWidget(panel)
    return panel, edits


def _levels(count):
    """``count`` enhancements over an original, newest first — the shape
    :func:`~origenerator.gallery.enhance.enhance_levels` produces."""
    return [
        EnhanceLevel(i, f"Enhance {i}", {"filename": f"e{i}.png", "subfolder": "image"})
        for i in range(count, 0, -1)
    ] + [EnhanceLevel(0, "Original", {"filename": "src.png", "subfolder": "image"})]


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


# --- the version list ------------------------------------------------------


def _buttons(widget):
    return widget._host.findChildren(QPushButton)


def test_an_unenhanced_image_shows_no_version_list(qtbot):
    versions = EnhanceVersions()
    qtbot.addWidget(versions)
    versions.show_levels(_levels(0))
    assert versions.isHidden()      # nothing to choose between


def test_levels_list_newest_first_with_the_newest_selected(qtbot):
    versions = EnhanceVersions()
    qtbot.addWidget(versions)
    versions.show_levels(_levels(2))
    buttons = _buttons(versions)
    assert [b.text() for b in buttons] == ["Enhance 2", "Enhance 1", "Original"]
    # The preview opens on the most-enhanced version, so that button starts lit.
    assert buttons[0].isChecked()
    assert not buttons[1].isChecked()


def test_clicking_a_level_reports_its_position(qtbot):
    versions = EnhanceVersions()
    qtbot.addWidget(versions)
    versions.show_levels(_levels(2))
    picked = []
    versions.level_selected.connect(picked.append)

    _buttons(versions)[2].click()   # the original

    assert picked == [2]


def test_a_levels_settings_ride_on_its_button(qtbot):
    versions = EnhanceVersions()
    qtbot.addWidget(versions)
    versions.show_levels([
        EnhanceLevel(1, "Enhance 1", {"filename": "e1.png"}, "2x · 20 steps"),
        EnhanceLevel(0, "Original", {"filename": "src.png"}),
    ])
    assert "2x · 20 steps" in _buttons(versions)[0].text()


def test_rebuilding_for_another_image_drops_the_old_buttons(qtbot):
    # Switching selection must not stack one image's levels under another's.
    versions = EnhanceVersions()
    qtbot.addWidget(versions)
    versions.show_levels(_levels(2))
    versions.show_levels(_levels(1))
    assert [b.text() for b in _buttons(versions)] == ["Enhance 1", "Original"]

from PyQt6.QtWidgets import QLabel, QPushButton

from origenerator.comfyui_client import ComfyUIClient
from origenerator.db import Database
from origenerator.gui.animated_strip import AnimatedVideoStrip
from origenerator.gui.generate_config_panel import GenerateConfigPanel
from origenerator.gui.inspect_panel import InspectPanel
from origenerator.gui.metadata_panel import MetadataPanel
from origenerator.gui.preview_widget import PreviewWidget
from origenerator.job_queue import JobQueue


def _panel(qtbot, tmp_path, *, client=True):
    db = Database(tmp_path / "t.db")
    p = InspectPanel(ComfyUIClient() if client else None, db, queue=JobQueue(db))
    qtbot.addWidget(p)
    return p


def test_exposes_the_sidebar_widgets_and_the_editable_form(qtbot, tmp_path):
    p = _panel(qtbot, tmp_path)
    assert isinstance(p.meta_title, QLabel)
    assert isinstance(p.estimate_label, QLabel)
    assert isinstance(p.preview, PreviewWidget)
    assert isinstance(p.meta_panel, MetadataPanel)
    assert isinstance(p.animated_strip, AnimatedVideoStrip)
    assert isinstance(p.evolver_btn, QPushButton)
    assert isinstance(p.config, GenerateConfigPanel)


def test_the_form_shares_the_one_preview(qtbot, tmp_path):
    # Live generation frames and the browsed generation land in the same widget.
    p = _panel(qtbot, tmp_path)
    assert p.config._preview is p.preview


def test_the_form_has_no_per_tab_strip(qtbot, tmp_path):
    p = _panel(qtbot, tmp_path)
    assert p.config._strip is None


def test_the_forms_own_estimate_is_hidden(qtbot, tmp_path):
    # Only the inspect estimate above the preview shows, so there aren't two.
    p = _panel(qtbot, tmp_path)
    assert p.config._estimate_label.isHidden()


def test_builds_for_a_read_only_gallery_with_no_client(qtbot, tmp_path):
    p = _panel(qtbot, tmp_path, client=False)
    assert p.config._generate_btn.isEnabled() is False  # inspect works, Generate is off


def test_leaves_the_shared_preview_to_the_controller(qtbot, tmp_path):
    # The controller drives the Inspect tab's preview from the browser selection,
    # so the embedded form must not autoshow its own recent-match over it.
    p = _panel(qtbot, tmp_path)
    assert p.config._autoshow_recent is False

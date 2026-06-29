from unittest.mock import patch

from origenerator.comfyui_client import ComfyUIClient
from origenerator.db import Database
from origenerator.gui.main_window import OrigeneratorWindow


def test_reuse_requested_opens_config_and_switches_tab(qtbot, tmp_path):
    client = ComfyUIClient()
    db = Database(tmp_path / "t.db")
    win = OrigeneratorWindow(client, db)
    qtbot.addWidget(win)

    with patch.object(
        win._generate_view, "open_config", wraps=win._generate_view.open_config
    ) as spy:
        win._gallery_view.reuse_requested.emit("wan22_i2v", {"positive_prompt": "hi"})

    spy.assert_called_once_with("wan22_i2v", {"positive_prompt": "hi"})
    assert win._tabs.currentWidget() is win._generate_view

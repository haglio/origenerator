from unittest.mock import MagicMock

from origenerator.db import Database
from origenerator.gui.generate_view import GenerateView


def _select_workflow(view, name):
    combo = view._workflow_combo
    for i in range(combo.count()):
        if combo.itemData(i) == name:
            combo.setCurrentIndex(i)
            return
    raise AssertionError(f"workflow {name!r} not offered")


def test_generate_blocks_when_input_image_missing(qtbot, tmp_path):
    client = MagicMock()
    view = GenerateView(client, Database(tmp_path / "t.db"))
    qtbot.addWidget(view)

    _select_workflow(view, "wan22_i2v")  # leaves Input Image blank
    view._on_generate()

    client.submit_job.assert_not_called()
    assert "image" in view._status_label.text().lower()
    assert view._db.list_generations() == []  # nothing recorded


def test_generate_submits_when_input_image_present(qtbot, tmp_path):
    client = MagicMock()
    client.submit_job.return_value = "comfy-prompt-id"
    view = GenerateView(client, Database(tmp_path / "t.db"))
    qtbot.addWidget(view)

    _select_workflow(view, "wan22_i2v")
    view._param_form.set_values({"input_image": "start.png"})
    view._on_generate()

    client.submit_job.assert_called_once()

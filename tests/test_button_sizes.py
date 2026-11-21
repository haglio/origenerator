from __future__ import annotations

import pytest
from PySide6.QtCore import QSize
from PySide6.QtWidgets import QAbstractButton, QWidget
from shared_ui.spacing import BUTTON_SIZE

from origenerator import ui_scale
from origenerator.app_state import AppState
from tests.test_core import _seed_combine_db, _window
from tests.test_fun_time_gallery import _session

OTHER_SIZES_WAITING_ON_HIS_RULING = {
    "action.image.add": "the plus after an item's image actions",
    "action.video.add": "the plus after an item's video actions",
}


def _named(widget: QWidget) -> list[str]:
    names, holder = [], widget
    while holder is not None and len(names) < 3:
        names.append(holder.objectName() or type(holder).__name__)
        holder = holder.parentWidget()
    return names


def _a_square_wearing_only_an_icon(button: QAbstractButton) -> bool:
    return (button.minimumSize() == button.maximumSize() and button.width() == button.height()
            and not button.text() and not button.icon().isNull())


def _waits(button: QAbstractButton) -> bool:
    return any(name in OTHER_SIZES_WAITING_ON_HIS_RULING for name in _named(button))


@pytest.mark.parametrize("in_fun_time", [False, True])
def test_every_square_icon_button_in_the_window_is_the_one_size(qtbot, tmp_path, in_fun_time):
    _seed_combine_db(tmp_path)
    win = _window(qtbot, tmp_path, AppState(tmp_path / "ui.json"),
                  fun_time=_session() if in_fun_time else None)
    view = win._gallery_view
    view.refresh()
    view.generate_pane.currentWidget().prefill("sdxl_t2i", {})
    view.generate_pane.open_config("wan22_i2v", {})
    edge = ui_scale.landing_at_the_huds_scale(BUTTON_SIZE, hosted=in_fun_time)

    another_size = sorted({
        f"{' < '.join(_named(button))}: {button.width()}"
        for button in win.findChildren(QAbstractButton)
        if _a_square_wearing_only_an_icon(button) and button.size() != QSize(edge, edge)
        and not _waits(button)})

    assert not another_size, (
        f"every square button that wears only an icon is {edge} across here, the size "
        "ui_scale.landing_at_the_huds_scale gives the Gallery pane buttons, so the window's "
        "buttons read as one set Standalone and in Fun Time alike; size these with it too: "
        + "; ".join(another_size))

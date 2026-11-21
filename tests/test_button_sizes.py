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
    "cornerButtonFace": "the star, the trash can and the rest over the corners of the item shown",
    "action.image.add": "the plus after an item's image actions",
    "action.video.add": "the plus after an item's video actions",
}
IN_A_SESSION_ONLY = {
    "borderedSet": "the pencil beside each of the Enhance pane's fixes, drawn the Standalone size",
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


def _waits(button: QAbstractButton, *, in_a_session: bool) -> bool:
    waiting = {**OTHER_SIZES_WAITING_ON_HIS_RULING, **(IN_A_SESSION_ONLY if in_a_session else {})}
    return any(name in waiting for name in _named(button))


@pytest.mark.parametrize("in_a_session", [False, True])
def test_every_square_icon_button_in_the_window_is_the_one_size(qtbot, tmp_path, in_a_session):
    _seed_combine_db(tmp_path)
    win = _window(qtbot, tmp_path, AppState(tmp_path / "ui.json"),
                  fun_time=_session() if in_a_session else None)
    view = win._gallery_view
    view.refresh()
    view.generate_pane.currentWidget().prefill("sdxl_t2i", {})
    view.generate_pane.open_config("wan22_i2v", {})
    edge = ui_scale.landing_at_the_huds_scale(BUTTON_SIZE, hosted=in_a_session)

    another_size = sorted({
        f"{' < '.join(_named(button))}: {button.width()}"
        for button in win.findChildren(QAbstractButton)
        if _a_square_wearing_only_an_icon(button) and button.size() != QSize(edge, edge)
        and not _waits(button, in_a_session=in_a_session)})

    assert not another_size, (
        f"every square button that wears only an icon is {edge} across here, the size "
        "ui_scale.landing_at_the_huds_scale gives the Gallery pane buttons, so the window's "
        "buttons read as one set Standalone and in a session alike; size these with it too: "
        + "; ".join(another_size))

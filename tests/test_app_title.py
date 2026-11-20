from __future__ import annotations

from PySide6.QtGui import QColor, QIcon, QPixmap
from PySide6.QtWidgets import QWidget
from shared_ui.palette import LOADING_ACCENT, PREVIEW_INK, as_hex
from shared_ui.preview import Preview
from shared_ui.spacing import BUTTON_SIZE

from origenerator.gui.app_title import AppTitle, under
from origenerator.gui.thin_divider import ThinDivider


def _an_icon() -> QIcon:
    drawn = QPixmap(64, 64)
    drawn.fill(QColor("white"))
    return QIcon(drawn)


def test_the_title_is_the_apps_icon_beside_its_name_in_bold_italic(qtbot):
    title = AppTitle("Origenerator", _an_icon(), None)
    qtbot.addWidget(title)

    lettering = title.name.font()
    assert (title.logo.pixmap().isNull(), title.logo.pixmap().width() <= BUTTON_SIZE * 2,
            title.name.text(), lettering.bold(), lettering.italic()) == (
        False, True, "Origenerator", True, True)


def test_the_name_is_the_loading_screens_red_and_a_previews_is_yellow(qtbot):
    production = AppTitle("Origenerator", _an_icon(), None)
    preview = AppTitle("Origenerator", _an_icon(), Preview(feature="a made-up feature"))
    qtbot.addWidget(production)
    qtbot.addWidget(preview)

    assert (as_hex(LOADING_ACCENT) in production.name.styleSheet(),
            as_hex(PREVIEW_INK) in preview.name.styleSheet()) == (True, True)


def test_production_has_nothing_to_say_on_a_hover(qtbot):
    title = AppTitle("Origenerator", _an_icon(), None)
    qtbot.addWidget(title)

    assert title.toolTip() == ""


def test_a_thin_divider_parts_the_title_from_what_sits_under_it(qtbot):
    title = AppTitle("Origenerator", QIcon(), None)
    content = QWidget()
    stacked = under(title, content)
    qtbot.addWidget(stacked)
    column = stacked.layout()

    assert [type(column.itemAt(n).widget()) for n in range(column.count())] == [
        AppTitle, ThinDivider, QWidget]

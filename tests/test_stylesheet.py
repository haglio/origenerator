from __future__ import annotations

from PyQt6.QtCore import QPoint
from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import (
    QApplication,
    QLabel,
    QMenu,
    QRadioButton,
    QSpinBox,
    QStyle,
    QStyleOptionSpinBox,
    QTabBar,
    QTreeWidget,
    QTreeWidgetItem,
)
from shared_ui.colors import (
    BG_BUTTON,
    BG_PRIMARY,
    BLUE,
    BORDER_SUBTLE,
    TEXT_MUTED,
    TEXT_PRIMARY,
    hovered,
)
from shared_ui.palette import PREVIEW_INK
from shared_ui.preview import Preview
from shared_ui.spacing import GAP_SMALL

from origenerator.gui.stylesheet import build_stylesheet, dress_application


def test_the_stylesheet_is_qss_with_every_shared_ui_token_resolved():
    qss = build_stylesheet()
    assert isinstance(qss, str)
    assert "QProgressBar::chunk" in qss
    assert "#" in qss


def test_a_tabs_close_mark_is_styled_flat_not_as_a_button():
    qss = build_stylesheet()
    rule = qss.split("QToolButton#tabCloseButton, QToolButton#sceneRemove {", 1)[1].split("}", 1)[0]
    assert "background-color: transparent" in rule
    assert "border: none" in rule
    assert "border-radius: 0" in rule


def test_stylesheet_greys_disabled_buttons():
    rule = build_stylesheet().split("QPushButton:disabled {", 1)[1].split("}", 1)[0]
    assert TEXT_MUTED.name() in rule
    assert TEXT_PRIMARY.name() not in rule


def test_stylesheet_greys_disabled_dropdown_items():
    assert "QComboBox QAbstractItemView::item:disabled" in build_stylesheet()


def test_stylesheet_styles_tooltips():
    # Native tooltips render unreadably on Windows 11 dark mode, so the sheet
    # must style QToolTip explicitly — with square corners, since a rounded
    # stylesheet tooltip paints artifact squares on Windows.
    qss = build_stylesheet()
    tooltip_rule = qss.split("QToolTip", 1)[1].split("}", 1)[0]
    assert "background-color" in tooltip_rule
    assert "border-radius" not in tooltip_rule



def test_stylesheet_styles_collapsible_section_headers():
    qss = build_stylesheet()
    rule = qss.split("QPushButton#foldingSectionHeader {", 1)[1].split("}", 1)[0]
    assert "background-color: transparent" in rule
    assert "border-width: 0 0 1px 0" in rule
    assert "border-radius: 0;" in rule
    pressed = qss.split("QPushButton#foldingSectionHeader:pressed {", 1)[1].split("}", 1)[0]
    assert "background-color" in pressed


def _menu_row_colors(qtbot):
    app = QApplication.instance()
    prior = app.styleSheet()
    app.setStyleSheet(build_stylesheet())
    try:
        menu = QMenu()
        qtbot.addWidget(menu)
        hovered = menu.addAction("Close others")
        other = menu.addAction("Close to the right")
        menu.show()
        menu.setActiveAction(hovered)
        image = menu.grab().toImage()
        return (image.pixelColor(menu.actionGeometry(hovered).center()),
                image.pixelColor(menu.actionGeometry(other).center()))
    finally:
        app.setStyleSheet(prior)


def test_a_menu_lights_the_row_under_the_cursor(qtbot):
    hovered, other = _menu_row_colors(qtbot)
    assert hovered == BLUE
    assert other != hovered


def test_a_menus_disabled_row_does_not_light_up():
    qss = build_stylesheet()
    rule = qss.split("QMenu::item:disabled:selected {", 1)[1].split("}", 1)[0]
    assert "background-color: transparent" in rule


def _radio_image(qtbot, checked: bool):
    app = QApplication.instance()
    prior = app.styleSheet()
    app.setStyleSheet(build_stylesheet())
    try:
        radio = QRadioButton("Video")
        qtbot.addWidget(radio)
        radio.setChecked(checked)
        radio.resize(radio.sizeHint())
        return radio.grab().toImage()
    finally:
        app.setStyleSheet(prior)


def _lightness(image, x: int) -> int:
    return image.pixelColor(x, image.height() // 2).lightness()


def test_a_selected_radio_shows_a_light_disc_inside_its_ring(qtbot):
    centre = 8
    assert _lightness(_radio_image(qtbot, checked=True), centre) > 200
    assert _lightness(_radio_image(qtbot, checked=False), centre) < 80
    assert _lightness(_radio_image(qtbot, checked=True), 1) < 100


def test_a_radios_ring_stays_visible_in_both_states(qtbot):
    for checked in (True, False):
        image = _radio_image(qtbot, checked=checked)
        assert max(_lightness(image, x) for x in (0, 1)) > BG_PRIMARY.lightness() + 30


def _spin_down_rect(spinner):
    option = QStyleOptionSpinBox()
    option.initFrom(spinner)
    option.rect = spinner.rect()
    option.subControls = (QStyle.SubControl.SC_SpinBoxUp
                          | QStyle.SubControl.SC_SpinBoxDown)
    return spinner.style().subControlRect(
        QStyle.ComplexControl.CC_SpinBox, option,
        QStyle.SubControl.SC_SpinBoxDown, spinner)


def _styled_spinner(qtbot):
    spinner = QSpinBox()
    qtbot.addWidget(spinner)
    spinner.setStyleSheet(build_stylesheet())
    spinner.resize(120, 44)
    return spinner


def test_the_step_down_button_lands_in_the_lower_right_corner(qtbot):
    spinner = _styled_spinner(qtbot)

    down = _spin_down_rect(spinner)

    assert down.center().y() > spinner.rect().center().y()
    assert down.center().x() > spinner.rect().center().x()


def test_the_step_down_buttons_outer_corner_is_rounded_off(qtbot):
    spinner = _styled_spinner(qtbot)
    down = _spin_down_rect(spinner)
    image = spinner.grab().toImage()

    assert image.pixelColor(down.bottomRight()) != BG_BUTTON
    assert image.pixelColor(down.bottomRight() - QPoint(5, 5)) == BG_BUTTON


def test_a_step_button_sits_one_step_lighter_under_the_pointer(qtbot, pointer):
    spinner = _styled_spinner(qtbot)
    with qtbot.waitExposed(spinner):
        spinner.show()
    down = _spin_down_rect(spinner)
    ground = down.bottomRight() - QPoint(5, 5)
    pointer.off(spinner)
    at_rest = spinner.grab().toImage().pixelColor(ground)
    pointer.on(spinner, down.center())

    assert spinner.grab().toImage().pixelColor(ground).name() == hovered(at_rest).name()


def _tab_bar_image(qtbot):
    app = QApplication.instance()
    prior = app.styleSheet()
    app.setStyleSheet(build_stylesheet())
    try:
        bar = QTabBar()
        qtbot.addWidget(bar)
        bar.addTab("Alpha")
        bar.addTab("Beta")
        bar.setCurrentIndex(0)
        bar.resize(bar.sizeHint())
        return bar.grab().toImage(), bar.tabRect(0), bar.tabRect(1)
    finally:
        app.setStyleSheet(prior)


def test_a_picked_row_in_the_table_of_contents_wears_the_familys_blue(qtbot):
    app = QApplication.instance()
    prior = app.styleSheet()
    app.setStyleSheet(build_stylesheet())
    try:
        tree = QTreeWidget()
        qtbot.addWidget(tree)
        for name in ("folder one", "folder two"):
            tree.addTopLevelItem(QTreeWidgetItem([name]))
        tree.resize(300, 120)
        with qtbot.waitExposed(tree):
            tree.show()
        tree.setCurrentItem(tree.topLevelItem(0))

        image = tree.viewport().grab().toImage()
        picked = tree.visualItemRect(tree.topLevelItem(0))
        other = tree.visualItemRect(tree.topLevelItem(1))

        assert image.pixelColor(picked.right() - 2, picked.center().y()) == BLUE
        assert image.pixelColor(other.right() - 2, other.center().y()) != BLUE
    finally:
        app.setStyleSheet(prior)


def test_the_selected_tab_is_underlined_and_the_others_are_not(qtbot):
    image, selected, other = _tab_bar_image(qtbot)
    low = selected.bottomLeft().y()

    assert image.pixelColor(selected.center().x(), low) == BLUE
    assert image.pixelColor(other.center().x(), low) != BLUE


def test_a_time_heading_is_ruled_off_above_like_a_search_sections_heading(qtbot):
    app = QApplication.instance()
    prior = app.styleSheet()
    app.setStyleSheet(build_stylesheet())
    try:
        heading = QLabel("Sat Sep 12, 7:10 PM – 7:40 PM")
        heading.setObjectName("tileGroupHeading")
        qtbot.addWidget(heading)
        heading.resize(300, heading.sizeHint().height())
        image = heading.grab().toImage()
    finally:
        app.setStyleSheet(prior)

    assert image.pixelColor(150, 0) == BORDER_SUBTLE


def test_a_hairline_still_separates_one_tab_from_the_next(qtbot):
    image, selected, _ = _tab_bar_image(qtbot)
    seam = selected.topRight().x()

    assert image.pixelColor(seam, selected.center().y()) == BORDER_SUBTLE


def test_dressing_the_app_hands_it_the_icon_every_window_wears(qapp):
    before = qapp.windowIcon()
    qapp.setWindowIcon(QIcon())
    try:
        dress_application(qapp, None)

        assert not qapp.windowIcon().isNull()
    finally:
        qapp.setWindowIcon(before)


def test_a_preview_hands_the_app_its_letter_in_the_preview_ink(qapp):
    before = qapp.windowIcon()
    try:
        dress_application(qapp, Preview(feature=None))

        side_of_the_o = qapp.windowIcon().pixmap(256, 256).toImage().pixelColor(48, 128)
        assert (side_of_the_o.red(), side_of_the_o.green(), side_of_the_o.blue()) == PREVIEW_INK
    finally:
        qapp.setWindowIcon(before)


def test_a_radio_keeps_its_word_the_familys_small_gap_from_its_own_circle(qapp):
    qapp.setStyleSheet(build_stylesheet())
    radio = QRadioButton("Kino")

    assert radio.style().pixelMetric(
        QStyle.PixelMetric.PM_RadioButtonLabelSpacing, None, radio) == GAP_SMALL

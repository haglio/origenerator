from origenerator.gui.stylesheet import build_stylesheet


def test_build_stylesheet_resolves_shared_ui_and_returns_qss():
    qss = build_stylesheet()
    assert isinstance(qss, str)
    # Colors come from shared_ui; a resolved import yields concrete hex values.
    assert "QProgressBar::chunk" in qss
    assert "#" in qss


def test_a_tabs_close_mark_is_styled_flat_not_as_a_button():
    # All a tab's ✕ is is the style's own mark sitting on the tab; the default
    # QToolButton look would box it in a raised, rounded border.
    qss = build_stylesheet()
    rule = qss.split("QToolButton#tabCloseButton {", 1)[1].split("}", 1)[0]
    assert "background-color: transparent" in rule
    assert "border: none" in rule
    assert "border-radius: 0" in rule


def test_stylesheet_greys_disabled_buttons():
    # Without an explicit :disabled rule a styled QPushButton ignores Qt's
    # disabled palette and never looks greyed out. The rule has to say something
    # different from the enabled one to be worth having, so it is the colour that
    # is asserted, not the presence of the selector: painting a disabled button in
    # the ordinary text colour leaves it looking perfectly pressable.
    from shared_ui.colors import TEXT_MUTED, TEXT_PRIMARY

    rule = build_stylesheet().split("QPushButton:disabled {", 1)[1].split("}", 1)[0]
    assert TEXT_MUTED.name() in rule
    assert TEXT_PRIMARY.name() not in rule


def test_stylesheet_greys_disabled_dropdown_items():
    # The popup view sets an unconditional item colour, which a disabled item would
    # otherwise inherit — leaving an unpickable act looking perfectly pickable.
    assert "QComboBox QAbstractItemView::item:disabled" in build_stylesheet()


def test_stylesheet_styles_tooltips():
    # Native tooltips render unreadably on Windows 11 dark mode, so the sheet
    # must style QToolTip explicitly — with square corners, since a rounded
    # stylesheet tooltip paints artifact boxes on Windows.
    qss = build_stylesheet()
    tooltip_rule = qss.split("QToolTip", 1)[1].split("}", 1)[0]
    assert "background-color" in tooltip_rule
    assert "border-radius" not in tooltip_rule


# That the launch applies this sheet to the QApplication — the reason tooltips
# render at all, since a QToolTip popup is a top-level widget no window-level
# sheet reaches — is pinned by running the launch and reading the sheet back off
# the application: tests/test_app.py, test_the_launch_dresses_the_application_in_
# the_stylesheet. It used to be asserted by grepping app.py for the call, which
# holds just as well with that call sitting in a comment.


def test_stylesheet_styles_collapsible_section_headers():
    # The param form's section headers are flat QPushButtons; without their own
    # rule they'd render as raised buttons and flash blue when toggled. What the
    # rule says is the point — a header given a border radius is the raised button
    # this exists to prevent, and the selector would still be there.
    qss = build_stylesheet()
    rule = qss.split("QPushButton#sectionHeader {", 1)[1].split("}", 1)[0]
    assert "background-color: transparent" in rule
    assert "border: none" in rule
    assert "border-radius: 0;" in rule
    pressed = qss.split("QPushButton#sectionHeader:pressed {", 1)[1].split("}", 1)[0]
    assert "background-color" in pressed  # and not Qt's own blue flash


def _menu_row_colors(qtbot):
    """(hovered row, unhovered row) as rendered under the app stylesheet.

    Rendered rather than read off the sheet: a stylesheet rule that never reaches
    a QMenu — they are top-level popups — looks identical in the string and shows
    nothing on screen, which is how the app's tooltips once went missing.
    """
    from PyQt6.QtWidgets import QApplication, QMenu

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
    # The app-wide QWidget rule paints a menu's items on the menu's own flat
    # background, so without this the row under the cursor looked exactly like the
    # rows either side of it and the menu said nothing about what a click hits.
    from shared_ui.colors import BLUE

    hovered, other = _menu_row_colors(qtbot)
    assert hovered == BLUE
    assert other != hovered


def test_a_menus_disabled_row_does_not_light_up():
    # Hovering something unclickable must not promise a click.
    qss = build_stylesheet()
    rule = qss.split("QMenu::item:disabled:selected {", 1)[1].split("}", 1)[0]
    assert "background-color: transparent" in rule


def _radio_image(qtbot, checked: bool):
    """A radio button rendered under the app stylesheet.

    Rendered rather than read off the sheet, for the same reason the menu rows
    are: what broke here was the platform's own drawing of the selected mark,
    which no rule in the string describes -- only the pixels say whether the
    mark is there.
    """
    from PyQt6.QtWidgets import QApplication, QRadioButton

    app = QApplication.instance()
    prior = app.styleSheet()
    app.setStyleSheet(build_stylesheet())
    try:
        radio = QRadioButton("Players")
        qtbot.addWidget(radio)
        radio.setChecked(checked)
        radio.resize(radio.sizeHint())
        return radio.grab().toImage()
    finally:
        app.setStyleSheet(prior)


def _lightness(image, x: int) -> int:
    """How light the pixel at ``x`` is, across the indicator's widest row."""
    return image.pixelColor(x, image.height() // 2).lightness()


def test_a_selected_radio_shows_a_light_disc_inside_its_ring(qtbot):
    # The whole failure: under the app sheet the platform painted the selected
    # mark dark on this dark ground, so picking Players or Genau left nothing on
    # screen saying which lane was picked. The disc has to stop short of the ring
    # as well -- one filling it edge to edge is a blob, not a radio button.
    centre = 8  # the middle of a 16px indicator, which sits at the widget's left
    assert _lightness(_radio_image(qtbot, checked=True), centre) > 200
    assert _lightness(_radio_image(qtbot, checked=False), centre) < 80
    assert _lightness(_radio_image(qtbot, checked=True), 1) < 100  # the gap


def test_a_radios_ring_stays_visible_in_both_states(qtbot):
    # The ring is what says there is a choice here at all, so the disc arriving
    # must not swallow it, and neither state may leave it as dark as the panel
    # behind it.
    from shared_ui.colors import BG_PRIMARY

    for checked in (True, False):
        image = _radio_image(qtbot, checked=checked)
        assert max(_lightness(image, x) for x in (0, 1)) > BG_PRIMARY.lightness() + 30

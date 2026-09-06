from origenerator.gui.stylesheet import build_stylesheet


def test_build_stylesheet_resolves_shared_ui_and_returns_qss():
    qss = build_stylesheet()
    assert isinstance(qss, str)
    # Colors come from shared_ui; a resolved import yields concrete hex values.
    assert "QProgressBar::chunk" in qss
    assert "#" in qss


def test_a_tabs_close_mark_is_styled_flat_not_as_a_button():
    # All a tab's ✕ is is the style's own mark sitting on the tab; the default
    # QToolButton look would wall it into a raised, rounded border. A scene card's
    # remove wears the same mark, under the same rule.
    qss = build_stylesheet()
    rule = qss.split("QToolButton#tabCloseButton, QToolButton#sceneRemove {", 1)[1].split("}", 1)[0]
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
    assert "border-width: 0 0 1px 0" in rule   # ruled off below, flat everywhere else
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


def _spin_down_rect(box):
    """Where the style puts a spin box's step-down sub-control.

    Asked of the style rather than worked out from the sheet: the sheet is one
    input to that answer and Qt's own default is the other, so the only thing
    that says where the button actually lands is the style itself.
    """
    from PyQt6.QtWidgets import QStyle, QStyleOptionSpinBox

    option = QStyleOptionSpinBox()
    option.initFrom(box)
    option.rect = box.rect()
    option.subControls = (QStyle.SubControl.SC_SpinBoxUp
                          | QStyle.SubControl.SC_SpinBoxDown)
    return box.style().subControlRect(
        QStyle.ComplexControl.CC_SpinBox, option,
        QStyle.SubControl.SC_SpinBoxDown, box)


def _styled_spin_box(qtbot):
    from PyQt6.QtWidgets import QSpinBox

    box = QSpinBox()
    qtbot.addWidget(box)
    box.setStyleSheet(build_stylesheet())
    box.resize(120, 44)
    return box


def test_the_step_down_button_lands_in_the_lower_right_corner(qtbot):
    # The sheet no longer places it by hand -- Qt's own default for a
    # down-button is already this corner -- so what holds it there is the style,
    # and the style is what this asks. Up must be the other one, or a sheet that
    # stacked them wrongly would satisfy a one-sided check.
    box = _styled_spin_box(qtbot)

    down = _spin_down_rect(box)

    assert down.center().y() > box.rect().center().y()
    assert down.center().x() > box.rect().center().x()


def test_the_step_down_buttons_outer_corner_is_rounded_off(qtbot):
    # It sits in the corner of a field whose own corners are rounded, so a square
    # one juts past the edge it is inside. Rendered, not read: the sheet spells
    # the radius one way and Qt either honors it or paints the corner solid.
    # Two-sided, because "not the button's ground" is also true of a button that
    # was never painted: five pixels in, the ground is exactly what it must be.
    from PyQt6.QtCore import QPoint
    from shared_ui.colors import BG_BUTTON

    box = _styled_spin_box(qtbot)
    down = _spin_down_rect(box)
    image = box.grab().toImage()

    assert image.pixelColor(down.bottomRight()) != BG_BUTTON
    assert image.pixelColor(down.bottomRight() - QPoint(5, 5)) == BG_BUTTON


def _tab_bar_image(qtbot):
    """A two-tab bar under the app stylesheet: its image and its two tab rects.

    The rects come back with the image because a tab's geometry is the styled
    geometry -- read after the sheet comes off and they describe a bar that was
    never rendered.
    """
    from PyQt6.QtWidgets import QApplication, QTabBar

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


def test_the_selected_tab_is_underlined_and_the_others_are_not(qtbot):
    # The rule that draws it sets three of the four edges at once, so a rewrite
    # of it can quietly take the mark away or paint it on every tab. Both halves
    # are asserted: the underline exists, and it belongs to one tab only.
    from shared_ui.colors import BLUE

    image, selected, other = _tab_bar_image(qtbot)
    low = selected.bottomLeft().y()

    assert image.pixelColor(selected.center().x(), low) == BLUE
    assert image.pixelColor(other.center().x(), low) != BLUE


def test_a_hairline_still_separates_one_tab_from_the_next(qtbot):
    # The same rule's other edge: it is what says which close mark belongs to
    # which tab, and it is drawn by the declaration the underline shares.
    from shared_ui.colors import BORDER_SUBTLE

    image, selected, _ = _tab_bar_image(qtbot)
    seam = selected.topRight().x()

    assert image.pixelColor(seam, selected.center().y()) == BORDER_SUBTLE

from origenerator.gui.stylesheet import build_stylesheet


def test_build_stylesheet_resolves_shared_ui_and_returns_qss():
    qss = build_stylesheet()
    assert isinstance(qss, str)
    # Colors come from shared_ui; a resolved import yields concrete hex values.
    assert "QProgressBar::chunk" in qss
    assert "#" in qss


def test_stylesheet_styles_the_subtab_add_button():
    # The Generate tab's "+" corner button is a QToolButton; keep it themed.
    assert "QToolButton" in build_stylesheet()


def test_stylesheet_greys_disabled_buttons():
    # Without an explicit :disabled rule a styled QPushButton ignores Qt's
    # disabled palette and never looks greyed out.
    assert "QPushButton:disabled" in build_stylesheet()


def test_stylesheet_greys_disabled_dropdown_items():
    # The popup view sets an unconditional item colour, which a disabled item would
    # otherwise inherit — leaving an unpickable act looking perfectly pickable.
    assert "QComboBox QAbstractItemView::item:disabled" in build_stylesheet()


def test_stylesheet_styles_tooltips():
    # A global QWidget background rule leaves QToolTip unreadable/blank unless it's
    # styled explicitly, so the toolbar buttons' tooltips never appear on hover.
    assert "QToolTip" in build_stylesheet()


def test_stylesheet_styles_collapsible_section_headers():
    # The param form's section headers are flat QPushButtons; without their own
    # rule they'd render as raised buttons and flash blue when toggled.
    qss = build_stylesheet()
    assert "QPushButton#sectionHeader" in qss
    assert "QPushButton#sectionHeader:pressed" in qss

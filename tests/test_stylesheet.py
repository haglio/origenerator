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
    # disabled palette and never looks greyed out.
    assert "QPushButton:disabled" in build_stylesheet()


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


def test_the_launch_applies_the_stylesheet_to_the_application():
    # QToolTip popups are top-level widgets: a window-level stylesheet never
    # reaches them, which is exactly how every tooltip in the app went missing
    # once — the QToolTip rule sat inert on the main window. The sheet must be
    # set on the QApplication, in main().
    from pathlib import Path
    app_source = (Path(__file__).resolve().parents[1]
                  / "origenerator" / "app.py").read_text(encoding="utf-8")
    assert "app.setStyleSheet(build_stylesheet())" in app_source


def test_stylesheet_styles_collapsible_section_headers():
    # The param form's section headers are flat QPushButtons; without their own
    # rule they'd render as raised buttons and flash blue when toggled.
    qss = build_stylesheet()
    assert "QPushButton#sectionHeader" in qss
    assert "QPushButton#sectionHeader:pressed" in qss

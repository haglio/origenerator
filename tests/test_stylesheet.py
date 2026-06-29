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


def test_stylesheet_colors_progress_bar_states():
    qss = build_stylesheet()
    for state in ("queued", "done", "error"):
        assert f'QProgressBar[barState="{state}"]::chunk' in qss


def test_stylesheet_greys_disabled_buttons():
    # Without an explicit :disabled rule a styled QPushButton ignores Qt's
    # disabled palette and never looks greyed out.
    assert "QPushButton:disabled" in build_stylesheet()

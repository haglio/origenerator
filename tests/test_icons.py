from origenerator.gui import icons


def test_toolbar_icons_render_with_normal_and_disabled_modes(qtbot):
    from PyQt6.QtCore import QSize
    from PyQt6.QtGui import QIcon

    for make in (icons.back_icon, icons.forward_icon, icons.undo_icon):
        icon = make()
        assert not icon.isNull()
        # A drawn (not blank) pixmap in both modes, so a disabled button dims cleanly.
        size = QSize(24, 24)
        assert not icon.pixmap(size, QIcon.Mode.Normal).isNull()
        assert not icon.pixmap(size, QIcon.Mode.Disabled).isNull()

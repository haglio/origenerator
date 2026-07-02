from origenerator.gui import icons


def test_level_badge_icons_render_for_each_level(qtbot):
    from PyQt6.QtCore import QSize

    # Every hierarchy level maps to a rendered chip, and the labels name exactly
    # the ones the gallery badges (workflow -> model -> LoRA -> source image).
    assert set(icons.LEVEL_LABELS) == {"workflow", "model", "lora", "source_image"}
    assert icons.LEVEL_LABELS["lora"] == "LoRA"
    assert icons.LEVEL_LABELS["source_image"] == "Source Image"
    for level in icons.LEVEL_LABELS:
        icon = icons.level_badge_icon(level)
        assert not icon.isNull()
        assert not icon.pixmap(QSize(16, 16)).isNull()


def test_toolbar_icons_render_with_normal_and_disabled_modes(qtbot):
    from PyQt6.QtCore import QSize
    from PyQt6.QtGui import QIcon

    makers = (icons.back_icon, icons.forward_icon, icons.undo_icon, icons.delete_icon,
              icons.clock_icon,
              lambda: icons.star_icon(filled=True), lambda: icons.star_icon(filled=False))
    for make in makers:
        icon = make()
        assert not icon.isNull()
        # A drawn (not blank) pixmap in both modes, so a disabled button dims cleanly.
        size = QSize(24, 24)
        assert not icon.pixmap(size, QIcon.Mode.Normal).isNull()
        assert not icon.pixmap(size, QIcon.Mode.Disabled).isNull()

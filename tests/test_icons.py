from origenerator.gui import icons


def _style_tab_close_pixmap():
    """The close mark the live style paints on a tab, drawn here independently."""
    from PyQt6.QtWidgets import QApplication, QStyle, QStyleOption
    from PyQt6.QtGui import QPixmap, QPainter
    from PyQt6.QtCore import Qt, QRect

    style = QApplication.style()
    size = style.pixelMetric(QStyle.PixelMetric.PM_TabCloseIndicatorWidth)
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    option = QStyleOption()
    option.rect = QRect(0, 0, size, size)
    option.state = QStyle.StateFlag.State_Enabled
    style.drawPrimitive(QStyle.PrimitiveElement.PE_IndicatorTabClose, option, painter)
    painter.end()
    return pixmap


def test_tab_close_icon_is_the_mark_the_style_paints_on_a_tab(qtbot):
    # The corner's close-all must wear a tab's own ✕, not a lookalike: the mark
    # comes from the style primitive QTabBar draws, at the size it draws it, so
    # the two controls read as one spelling of "close" rather than two.
    expected = _style_tab_close_pixmap()
    rendered = icons.tab_close_icon().pixmap(expected.size())
    assert not rendered.isNull()
    assert rendered.toImage() == expected.toImage()


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


def test_media_type_badges_render_for_image_and_video(qtbot):
    # The Recents shelf marks each tile image-or-video with a small corner badge;
    # both types must draw a non-blank pixmap so neither shows an empty square.
    image_badge = icons.media_type_badge("image")
    video_badge = icons.media_type_badge("video")
    assert not image_badge.isNull() and image_badge.width() > 0
    assert not video_badge.isNull() and video_badge.width() > 0
    # The two glyphs differ, so an image is never mistaken for a video.
    assert image_badge.toImage() != video_badge.toImage()


def test_corner_badges_wear_the_star_green_and_the_enhance_yellow(qtbot):
    from shared_ui.colors import AMBER, GREEN

    # The star is green because Fun Time's favorite ★ is (shared_ui's GREEN is
    # the value its HUD paints), so one color means "bookmarked" in both apps —
    # which leaves the enhanced tile's plus this palette's yellow, since the two
    # badges can sit on one tile and blue is genau's across this family. Both
    # marks are solid at their center, so the middle pixel is the color.
    star = icons.star_badge().toImage()
    plus = icons.enhance_badge().toImage()
    assert star.pixelColor(star.width() // 2, star.height() // 2) == GREEN
    assert plus.pixelColor(plus.width() // 2, plus.height() // 2) == AMBER


def test_a_starred_folders_star_is_the_same_green(qtbot):
    from PyQt6.QtCore import QSize
    from PyQt6.QtGui import QIcon

    from shared_ui.colors import GREEN

    # The tree paints a starred leaf (and the Starred shelf) with the filled star,
    # so it wears the badge's green: one color for "starred", tile or folder row.
    filled = icons.star_icon(filled=True).pixmap(QSize(48, 48), QIcon.Mode.Normal)
    assert filled.toImage().pixelColor(24, 25) == GREEN
    # The outline is the offer to star, not a thing that is starred, so it stays
    # the chrome's gray — and it dims like every other icon when disabled.
    outline = icons.star_icon(filled=False)
    assert outline.pixmap(QSize(48, 48), QIcon.Mode.Normal).toImage() \
        != filled.toImage()


def test_reroll_seed_icons_render_and_differ_by_media(qtbot):
    from PyQt6.QtCore import QSize

    # The i2v hover controls: a video-seed and an image-seed re-roll glyph, each
    # a non-blank pixmap, and visibly distinct so one isn't mistaken for the other.
    video = icons.reroll_seed_icon("video")
    image = icons.reroll_seed_icon("image")
    size = QSize(24, 24)
    assert not video.pixmap(size).isNull()
    assert not image.pixmap(size).isNull()
    assert video.pixmap(size).toImage() != image.pixmap(size).toImage()


def test_toolbar_icons_render_with_normal_and_disabled_modes(qtbot):
    from PyQt6.QtCore import QSize
    from PyQt6.QtGui import QIcon

    makers = (icons.back_icon, icons.forward_icon, icons.undo_icon, icons.delete_icon,
              icons.clock_icon, icons.audio_icon, icons.osr2_icon,
              lambda: icons.star_icon(filled=True), lambda: icons.star_icon(filled=False))
    for make in makers:
        icon = make()
        assert not icon.isNull()
        # A drawn (not blank) pixmap in both modes, so a disabled button dims cleanly.
        size = QSize(24, 24)
        assert not icon.pixmap(size, QIcon.Mode.Normal).isNull()
        assert not icon.pixmap(size, QIcon.Mode.Disabled).isNull()


def test_experiment_icons_render_and_verdicts_differ(qtbot):
    from PyQt6.QtCore import QSize
    from PyQt6.QtGui import QIcon

    # The Experiments shelf marker draws in both modes like the other shelves'.
    flask = icons.flask_icon()
    size = QSize(24, 24)
    assert not flask.pixmap(size, QIcon.Mode.Normal).isNull()
    assert not flask.pixmap(size, QIcon.Mode.Disabled).isNull()
    # The review hover controls: keep and reject, non-blank and visibly distinct.
    keep = icons.experiment_verdict_icon("up")
    reject = icons.experiment_verdict_icon("down")
    assert not keep.pixmap(size).isNull()
    assert not reject.pixmap(size).isNull()
    assert keep.pixmap(size).toImage() != reject.pixmap(size).toImage()

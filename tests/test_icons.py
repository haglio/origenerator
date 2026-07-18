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


def test_media_type_badges_render_for_image_and_video(qtbot):
    # The Recents shelf marks each tile image-or-video with a small corner badge;
    # both types must draw a non-blank pixmap so neither shows an empty square.
    image_badge = icons.media_type_badge("image")
    video_badge = icons.media_type_badge("video")
    assert not image_badge.isNull() and image_badge.width() > 0
    assert not video_badge.isNull() and video_badge.width() > 0
    # The two glyphs differ, so an image is never mistaken for a video.
    assert image_badge.toImage() != video_badge.toImage()


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
              icons.clock_icon,
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

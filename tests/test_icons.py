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

    # Every badged level maps to a rendered chip: the four recipe levels
    # (workflow -> model -> LoRA -> source image) and the two media roots.
    assert set(icons.LEVEL_LABELS) == {
        "workflow", "model", "lora", "source_image", "image", "video"}
    assert icons.LEVEL_LABELS["lora"] == "LoRA"
    assert icons.LEVEL_LABELS["source_image"] == "Source Image"
    assert icons.LEVEL_LABELS["image"] == "Images"
    for level in icons.LEVEL_LABELS:
        icon = icons.level_badge_icon(level)
        assert not icon.isNull()
        assert not icon.pixmap(QSize(16, 16)).isNull()


def test_the_media_roots_badge_with_their_own_glyphs(qtbot):
    # Images and Videos share a parent in the tree, so each carries a badge in
    # the same slot as the recipe levels — the play/photo glyphs their own items
    # wear, telling them apart at a glance and apart from the lettered chips.
    image = icons.level_badge_icon("image").pixmap(48, 48).toImage()
    video = icons.level_badge_icon("video").pixmap(48, 48).toImage()
    workflow = icons.level_badge_icon("workflow").pixmap(48, 48).toImage()
    assert image != video          # a photo is never mistaken for a play triangle
    assert image != workflow       # nor either of them for a lettered chip


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

    makers = (icons.back_icon, icons.forward_icon, icons.undo_icon, icons.redo_icon,
              icons.delete_icon, icons.clock_icon, icons.audio_icon, icons.stroke_icon,
              icons.autoloop_icon, icons.slideshow_icon, icons.enhance_icon,
              icons.custom_folder_icon,
              lambda: icons.star_icon(filled=True), lambda: icons.star_icon(filled=False))
    for make in makers:
        icon = make()
        assert not icon.isNull()
        # A drawn (not blank) pixmap in both modes, so a disabled button dims cleanly.
        size = QSize(24, 24)
        assert not icon.pixmap(size, QIcon.Mode.Normal).isNull()
        assert not icon.pixmap(size, QIcon.Mode.Disabled).isNull()


def test_the_bank_glyphs_are_all_different_marks(qtbot):
    from PyQt6.QtCore import QSize

    # Icon-only buttons are only as good as the glyphs telling each other apart,
    # and two of these were near-identical before: undo against auto-generate
    # (both a circular arrow), and undo against the redo it now sits beside.
    size = QSize(24, 24)
    drawn = {
        name: make().pixmap(size).toImage()
        for name, make in (
            ("back", icons.back_icon), ("forward", icons.forward_icon),
            ("undo", icons.undo_icon), ("redo", icons.redo_icon),
            ("auto", icons.autoloop_icon), ("slideshow", icons.slideshow_icon),
            ("enhance", icons.enhance_icon), ("delete", icons.delete_icon),
            ("audio", icons.audio_icon), ("osr2", icons.stroke_icon),
            ("group", icons.custom_folder_icon),
            ("star", lambda: icons.star_icon(filled=True)),
        )
    }
    names = sorted(drawn)
    for i, first in enumerate(names):
        for second in names[i + 1:]:
            assert drawn[first] != drawn[second], f"{first} and {second} draw alike"


def test_undo_and_redo_carry_their_heads_on_opposite_sides(qtbot):
    from PyQt6.QtCore import QSize

    # The pair is one drawing mirrored, and the arrowhead is what the mirror
    # moves: undo's fills the top-left, redo's the top-right. That difference has
    # to be big — the small head this replaced left the two all but identical at
    # button size — so each side carries at least half again the other's ink.
    size = QSize(48, 48)
    undo_left, undo_right = _top_corner_ink(icons.undo_icon().pixmap(size))
    redo_left, redo_right = _top_corner_ink(icons.redo_icon().pixmap(size))
    assert undo_left > undo_right * 1.5
    assert redo_right > redo_left * 1.5


def _top_corner_ink(pixmap) -> tuple[int, int]:
    """How much is drawn in the glyph's top-left and top-right corners."""
    image = pixmap.toImage()
    half, third = image.width() // 2, image.height() // 3
    left = right = 0
    for y in range(third):
        for x in range(image.width()):
            if image.pixelColor(x, y).alpha() > 128:
                if x < half:
                    left += 1
                else:
                    right += 1
    return left, right


def test_the_bank_colors_its_act_on_this_trio(qtbot):
    from PyQt6.QtCore import QSize
    from PyQt6.QtGui import QIcon
    from shared_ui.colors import AMBER, GREEN, RED, TEXT_MUTED

    # Star green, enhance yellow, delete red — the colors the corner badges wear,
    # so a button and the mark it leaves on a tile are one symbol. And every one
    # of them still dims to the same muted gray when it has nothing to act on, so
    # a dead button never reads as a dimmer shade of its color.
    size = QSize(48, 48)
    for icon, color in ((icons.star_icon(filled=True), GREEN),
                        (icons.enhance_icon(), AMBER),
                        (icons.delete_icon(), RED)):
        assert _dominant_color(icon.pixmap(size, QIcon.Mode.Normal)) == color.rgb()
        muted = _dominant_color(icon.pixmap(size, QIcon.Mode.Disabled))
        assert muted == TEXT_MUTED.rgb()


def _dominant_color(pixmap) -> int:
    """The most common fully-opaque pixel in a rendered glyph — its ink."""
    from collections import Counter

    image = pixmap.toImage()
    counts = Counter(
        image.pixel(x, y)
        for y in range(image.height()) for x in range(image.width())
        if image.pixelColor(x, y).alpha() == 255
    )
    return counts.most_common(1)[0][0]


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

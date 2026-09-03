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

    # Every badged level maps to a rendered chip: the four folder levels,
    # workflow -> model -> LoRA -> source image.
    assert set(icons.LEVEL_LABELS) == {
        "workflow", "model", "lora", "source_image"}
    assert icons.LEVEL_LABELS["lora"] == "LoRA"
    assert icons.LEVEL_LABELS["source_image"] == "Source Image"
    for level in icons.LEVEL_LABELS:
        icon = icons.level_badge_icon(level)
        assert not icon.isNull()
        assert not icon.pixmap(QSize(16, 16)).isNull()


def test_each_level_badge_is_tellable_from_its_siblings(qtbot):
    # The chips sit in one slot down the tree, so no two levels may draw the
    # same mark — that slot is the whole of what says which level a row is.
    drawn = [icons.level_badge_icon(level).pixmap(48, 48).toImage()
             for level in icons.LEVEL_LABELS]
    for i, one in enumerate(drawn):
        for other in drawn[i + 1:]:
            assert one != other


def test_media_type_badges_render_for_image_and_video(qtbot):
    # The Recents shelf marks each tile image-or-video with a small corner badge;
    # both types must draw a non-blank pixmap so neither shows an empty square.
    image_badge = icons.media_type_badge("image")
    video_badge = icons.media_type_badge("video")
    assert not image_badge.isNull() and image_badge.width() > 0
    assert not video_badge.isNull() and video_badge.width() > 0
    # The two glyphs differ, so an image is never mistaken for a video.
    assert image_badge.toImage() != video_badge.toImage()


def test_the_orientation_marks_are_one_frame_and_its_quarter_turn(qtbot):
    # The pair over the table of contents' two halves says which shape each half
    # holds, and it says it by BEING that shape: an upright frame and a
    # lying-down one, each the other transposed. Both are drawn in one square
    # box, so the words beside them start at the same x.
    portrait = icons.orientation_mark("portrait")
    landscape = icons.orientation_mark("landscape")
    assert portrait.size() == landscape.size()
    assert portrait.width() == portrait.height()

    tall, wide = _ink_bounds(portrait), _ink_bounds(landscape)
    assert tall[1] > tall[0]
    assert wide[0] > wide[1]
    assert tall == wide[::-1]


def test_an_orientation_mark_is_a_frame_and_not_a_filled_block(qtbot):
    # A frame, like the family's screen and photo marks -- what it stands for is
    # a region a picture goes in. Filled, it would read as a swatch, and the
    # rounded corners that say "screen" would be lost against the heading's word.
    from shared_ui.colors import TEXT_PRIMARY

    image = icons.orientation_mark("portrait").toImage()
    middle = image.pixelColor(image.width() // 2, image.height() // 2)
    assert middle.alpha() == 0                       # hollow through the center
    assert _dominant_color(icons.orientation_mark("portrait")) == TEXT_PRIMARY.rgb()


def _ink_bounds(pixmap) -> tuple[int, int]:
    """How wide and how tall what is drawn in *pixmap* actually is."""
    image = pixmap.toImage()
    drawn = [(x, y)
             for y in range(image.height()) for x in range(image.width())
             if image.pixelColor(x, y).alpha() > 40]
    xs, ys = [x for x, _ in drawn], [y for _, y in drawn]
    return max(xs) - min(xs) + 1, max(ys) - min(ys) + 1


def _corner_image(icon):
    from PyQt6.QtCore import QSize
    from PyQt6.QtGui import QIcon

    return icon.pixmap(QSize(48, 48), QIcon.Mode.Normal).toImage()


def test_corner_controls_wear_the_star_green_and_the_enhance_yellow(qtbot):
    from shared_ui.colors import AMBER, GREEN

    # The star is green because Fun Time's favorite ★ is (shared_ui's GREEN is
    # the value its HUD paints), so one color means "bookmarked" in both apps —
    # which leaves the enhanced picture's plus this palette's yellow, since the
    # two can sit on one tile and blue is genau's across this family. Both marks
    # are solid at their center, so the middle pixel is the color.
    star = _corner_image(icons.corner_star_icon(starred=True, armed=False))
    plus = _corner_image(icons.corner_enhance_icon(icons.ENHANCE_HELD, armed=False))
    assert star.pixelColor(24, 25) == GREEN
    assert plus.pixelColor(24, 24) == AMBER


def test_a_corner_control_reports_its_state_hollow_or_filled(qtbot):
    # The mark is the badge and the button at once, so what is filled says what
    # is true: an unstarred item's star is an outline with nothing in the middle,
    # and an image with no enhancement yet wears the hollow plus.
    unstarred = _corner_image(icons.corner_star_icon(starred=False, armed=False))
    assert unstarred.pixelColor(24, 25).alpha() < 32
    open_plus = _corner_image(icons.corner_enhance_icon(icons.ENHANCE_OPEN,
                                                        armed=False))
    assert open_plus.pixelColor(24, 24).alpha() < 32


def test_an_image_that_can_take_another_enhancement_shows_both_at_once(qtbot):
    from shared_ui.colors import AMBER

    # A hollow plus with the one it already holds as a yellow shadow behind it:
    # the middle stays empty like the plain hollow one, and the amber shows out
    # from under it down and to the right.
    more = _corner_image(icons.corner_enhance_icon(icons.ENHANCE_MORE, armed=False))
    assert more.pixelColor(24, 24).alpha() < 32          # still hollow
    ambers = [
        (x, y)
        for y in range(48) for x in range(48)
        if more.pixelColor(x, y) == AMBER
    ]
    assert ambers, "the enhancement it already holds never showed"
    assert max(x for x, _y in ambers) > 24 + 12          # …out to the right
    assert max(y for _x, y in ambers) > 24 + 12          # …and below


def test_arming_a_corner_control_changes_its_mark(qtbot):
    from shared_ui.colors import RED

    # Hovering says "this is a button" — the trash can in the red every delete in
    # this app wears, the others in the light gray that only means "armed".
    rest = _corner_image(icons.corner_trash_icon(armed=False))
    armed = _corner_image(icons.corner_trash_icon(armed=True))
    assert rest != armed
    assert any(armed.pixelColor(x, y) == RED
               for y in range(48) for x in range(48))
    star_rest = _corner_image(icons.corner_star_icon(starred=False, armed=False))
    star_armed = _corner_image(icons.corner_star_icon(starred=False, armed=True))
    assert star_rest != star_armed


def test_a_spent_enhance_corner_keeps_its_look_when_it_is_disabled(qtbot):
    from PyQt6.QtCore import QSize
    from PyQt6.QtGui import QIcon

    # It is dead because it is a finished statement — this image already holds the
    # version you would be asking for — so Qt's usual fade would read as a fault.
    icon = icons.corner_enhance_icon(icons.ENHANCE_HELD, armed=False)
    normal = icon.pixmap(QSize(48, 48), QIcon.Mode.Normal).toImage()
    disabled = icon.pixmap(QSize(48, 48), QIcon.Mode.Disabled).toImage()
    assert normal == disabled


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
    # Auto-generate wears a ring again, so this is the check that its bolt is
    # doing the work of telling it from the two arcs three buttons away.
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


def test_every_toolbar_mark_is_the_familys_shared_glyph(qtbot):
    from PyQt6.QtCore import QSize
    from PyQt6.QtGui import QIcon

    from shared_ui.colors import AMBER, GREEN, RED, TEXT_PRIMARY
    from shared_ui.icons import glyph_pixmap

    # The reason the glyphs left this module: a drawing kept here is a drawing
    # that can drift from Fun Time's copy of it, and the two apps' microphones
    # had already drifted into different shapes on one screen. So every button's
    # mark has to BE the family glyph, pixel for pixel -- what this app still
    # chooses is only which mark and in what color.
    cases = (
        (icons.back_icon(), "chevron_left", TEXT_PRIMARY),
        (icons.forward_icon(), "chevron_right", TEXT_PRIMARY),
        (icons.undo_icon(), "undo_arrow", TEXT_PRIMARY),
        (icons.redo_icon(), "redo_arrow", TEXT_PRIMARY),
        (icons.autoloop_icon(), "bolt_ring", TEXT_PRIMARY),
        (icons.slideshow_icon(), "slideshow", TEXT_PRIMARY),
        (icons.enhance_icon(), "plus", AMBER),
        (icons.mic_icon(), "mic", TEXT_PRIMARY),
        (icons.stroke_icon(), "wave", TEXT_PRIMARY),
        (icons.audio_icon(), "speaker", TEXT_PRIMARY),
        (icons.trash_icon(), "trash", TEXT_PRIMARY),
        (icons.delete_icon(), "trash", RED),
        (icons.star_icon(filled=True), "star", GREEN),
        (icons.star_icon(filled=False), "star_outline", TEXT_PRIMARY),
        (icons.clock_icon(), "clock", TEXT_PRIMARY),
        (icons.flask_icon(), "flask", TEXT_PRIMARY),
        (icons.custom_folder_icon(), "folder", TEXT_PRIMARY),
    )
    for icon, name, color in cases:
        drawn = icon.pixmap(QSize(48, 48), QIcon.Mode.Normal).toImage()
        assert drawn == glyph_pixmap(name, 48, color).toImage(), name


def test_the_tile_hover_controls_wear_shared_marks_too(qtbot):
    from PyQt6.QtCore import QSize
    from PyQt6.QtGui import QColor

    from shared_ui.icons import glyph_pixmap

    # The white line art on a thumbnail's hover buttons is the same family mark
    # the toolbar wears, in the white these read in over a picture -- not a
    # second set of drawings kept for the tiles.
    white = QColor(255, 255, 255)
    for icon, name in ((icons.experiment_verdict_icon("up"), "check"),
                       (icons.experiment_verdict_icon("down"), "cross"),
                       (icons.recovery_action_icon("restore"), "undo_arrow"),
                       (icons.recovery_action_icon("purge"), "trash")):
        drawn = icon.pixmap(QSize(48, 48)).toImage()
        assert drawn == glyph_pixmap(name, 48, white).toImage(), name

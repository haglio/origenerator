from __future__ import annotations

import ast
from collections import Counter
from pathlib import Path

from PySide6.QtCore import QSize
from PySide6.QtGui import QColor, QIcon, QPalette
from shared_ui.colors import GREEN, RED, TEXT_MUTED, TEXT_PRIMARY, WHITE, YELLOW, family_palette
from shared_ui.icon_geometry import icon_names
from shared_ui.icons import icon_pixmap, qt_icon
from shared_ui.spacing import BUTTON_FILLING_ICON

import origenerator
from origenerator.gallery.collection import LATEST_KEY
from origenerator.gallery.shapes import BOTH, LANDSCAPE, PORTRAIT
from origenerator.gui import icons
from origenerator.media import MediaType


def _drawn_by(monkeypatch, drawing: str) -> list:
    drawn = []
    real = getattr(icons, drawing)
    monkeypatch.setattr(icons, drawing,
                        lambda *args, **kwargs: drawn.append(args) or real(*args, **kwargs))
    return drawn


def test_a_collections_mark_is_drawn_once_however_many_folders_wear_it(qtbot, monkeypatch):
    drawn = _drawn_by(monkeypatch, "qt_icon")
    icons.collection_icon.cache_clear()

    for _ in range(3):
        icons.collection_icon(icons.EXPERIMENTS_KEY)

    assert drawn == [("flask",)]


def test_a_toc_initial_is_drawn_once_however_many_rows_wear_it(qtbot, monkeypatch):
    drawn = _drawn_by(monkeypatch, "_render_toc_initial")
    icons.toc_initial_icon.cache_clear()

    for _ in range(3):
        icons.toc_initial_icon("lora")

    assert drawn == [icons._TOC_INITIALS["lora"]], (
        "the same few TOC initials decorate many TOC rows and Gallery pane tiles, so each is "
        "drawn once")


def test_tab_close_icon_is_the_familys_cross(qtbot):
    assert (icons.tab_close_icon().pixmap(16).toImage()
            == qt_icon("cross").pixmap(16).toImage())


def test_toc_initial_icons_render_for_each_level(qtbot):
    assert set(icons.LEVEL_LABELS) == {
        "workflow", "model", "lora", "source_image"}
    assert icons.LEVEL_LABELS["lora"] == "LoRA"
    assert icons.LEVEL_LABELS["source_image"] == "Source Image"
    for level in icons.LEVEL_LABELS:
        icon = icons.toc_initial_icon(level)
        assert not icon.isNull()
        assert not icon.pixmap(QSize(16, 16)).isNull()


def test_a_lora_folder_wears_an_l(qtbot):
    drawn = icons.toc_initial_icon("lora").pixmap(48, 48).toImage()
    assert drawn == QIcon(icons._render_toc_initial("L", YELLOW)).pixmap(48, 48).toImage()


def test_each_toc_initial_is_tellable_from_its_siblings(qtbot):
    drawn = [icons.toc_initial_icon(level).pixmap(48, 48).toImage()
             for level in icons.LEVEL_LABELS]
    for i, one in enumerate(drawn):
        for other in drawn[i + 1:]:
            assert one != other, (
                "each level's TOC initial is its own, so a TOC row or a Gallery pane tile says "
                "which level it is without anyone counting indentation")


def test_item_type_icons_render_for_image_and_video(qtbot):
    image_icon = icons.item_type_icon(MediaType.IMAGE)
    video_icon = icons.item_type_icon(MediaType.VIDEO)
    assert not image_icon.isNull()
    assert image_icon.width() > 0
    assert not video_icon.isNull()
    assert video_icon.width() > 0
    assert image_icon.toImage() != video_icon.toImage()


def test_an_item_type_mark_is_a_white_glyph_on_a_translucent_dark_ground(qtbot):
    for media_type in (MediaType.IMAGE, MediaType.VIDEO):
        drawn = icons.item_type_icon(media_type).toImage()
        ground = drawn.pixelColor(drawn.width() // 2, 3)
        brightest = max((drawn.pixelColor(x, y) for x in range(drawn.width())
                         for y in range(drawn.height())), key=QColor.lightness)

        assert (ground.lightness() < 64, 0 < ground.alpha() < 255, brightest.rgba()) == (
            True, True, QColor(WHITE).rgba()), (
            "the item type mark is a white glyph on a translucent dark ground, so it reads over "
            "a thumbnail of any color")


def test_the_mark_among_words_is_drawn_without_the_ground(qtbot):
    for media_type in (MediaType.IMAGE, MediaType.VIDEO):
        drawn = icons.media_type_icon(media_type).pixmap(icons._ITEM_TYPE_ICON_SIZE).toImage()
        ground = drawn.pixelColor(drawn.width() // 2, 3)
        inked = any(drawn.pixelColor(x, y).alpha() > 40 for x in range(drawn.width())
                    for y in range(drawn.height()))

        assert (ground.alpha(), inked) == (0, True), (
            "the mark in a TOC row or a tab's title sits among words, where the dark ground would "
            "be a black square, so it is drawn bare")


def test_a_folder_lately_worked_in_wears_a_dot_in_the_familys_accent_color(qtbot):
    accent = family_palette().color(QPalette.ColorRole.Accent)

    assert (icons.recent_mark_icon().pixmap(icons._SIZE).toImage()
            == icon_pixmap("disc", icons._SIZE, accent).toImage()), (
        "a dot rather than a glyph, in the family's one accent color: it says a folder is one of "
        "the few last worked in and nothing else")


def test_the_side_marks_are_one_frame_and_its_quarter_turn(qtbot):
    portrait = icons.shape_mark("portrait")
    landscape = icons.shape_mark("landscape")
    assert portrait.size() == landscape.size(), (
        "both marks are drawn on one square canvas, so the words beside them start at the same "
        "x")
    assert portrait.width() == portrait.height(), (
        "both marks are drawn on one square canvas, so the words beside them start at the same "
        "x")

    tall, wide = _ink_bounds(portrait), _ink_bounds(landscape)
    assert tall[1] > tall[0]
    assert wide[0] > wide[1]
    assert tall == wide[::-1]


def test_a_side_mark_is_a_frame_and_not_a_filled_block(qtbot):
    image = icons.shape_mark("portrait").toImage()
    middle = image.pixelColor(image.width() // 2, image.height() // 2)
    assert middle.alpha() == 0, (
        "a frame stands for a region an image goes in; filled, it would read as a swatch")
    assert _dominant_color(icons.shape_mark("portrait")) == TEXT_PRIMARY.rgb()


def test_the_separate_mark_fits_the_square_it_is_drawn_on(qtbot):
    assert not _ink_at_the_edges(icons.separate_mark(BUTTON_FILLING_ICON))


def test_each_side_wears_the_familys_mark_of_its_shape_at_the_size_it_is_shown(qtbot):
    marks = {PORTRAIT: "portrait", LANDSCAPE: "landscape", BOTH: "portrait_and_landscape"}

    for side, mark in marks.items():
        for size in (icons.MARK_BESIDE_A_WORD, BUTTON_FILLING_ICON):
            assert (icons.shape_mark(side, size).toImage()
                    == icon_pixmap(mark, size, TEXT_PRIMARY).toImage()), (side, size)
    assert (icons.separate_mark(BUTTON_FILLING_ICON).toImage()
            == icon_pixmap("portrait_beside_landscape", BUTTON_FILLING_ICON, TEXT_PRIMARY).toImage())


def test_the_tocs_favorites_enhanced_and_trash_wear_their_colors(qtbot):
    for collection, name, color in ((icons.FAVORITES_KEY, "star", GREEN),
                                    (icons.ENHANCED_KEY, "plus", YELLOW),
                                    (icons.TRASH_KEY, "trash", RED)):
        drawn = icons.collection_icon(collection).pixmap(QSize(48, 48)).toImage()
        assert drawn == icon_pixmap(name, 48, color).toImage(), name


def test_a_collection_mark_is_drawn_once():
    assert icons.collection_icon(LATEST_KEY) is icons.collection_icon(LATEST_KEY), (
        "one redraw of the TOC asked for these 1,280 times")


def _ink_at_the_edges(pixmap) -> bool:
    image = pixmap.toImage()
    last_x, last_y = image.width() - 1, image.height() - 1
    border = ([(x, 0) for x in range(image.width())]
              + [(x, last_y) for x in range(image.width())]
              + [(0, y) for y in range(image.height())]
              + [(last_x, y) for y in range(image.height())])
    return any(image.pixelColor(x, y).alpha() > 40 for x, y in border)


def _ink_bounds(pixmap) -> tuple[int, int]:
    image = pixmap.toImage()
    drawn = [(x, y)
             for y in range(image.height()) for x in range(image.width())
             if image.pixelColor(x, y).alpha() > 40]
    xs, ys = [x for x, _ in drawn], [y for _, y in drawn]
    return max(xs) - min(xs) + 1, max(ys) - min(ys) + 1


def _corner_image(icon):
    return icon.pixmap(QSize(48, 48), QIcon.Mode.Normal).toImage()


def test_corner_controls_wear_the_star_green_and_the_enhance_yellow(qtbot):
    star = _corner_image(icons.corner_star_icon(favorite=True, armed=False))
    plus = _corner_image(icons.corner_enhance_icon(icons.ENHANCE_HELD, armed=False))
    assert star.pixelColor(24, 25) == GREEN, (
        "the star's green is Fun Time's, so one color means favorited in both apps; both marks "
        "are solid at their center, so the middle pixel is the color")
    assert plus.pixelColor(24, 24) == YELLOW, (
        "the plus is yellow: green is the star's and the two can sit on one tile, and blue is "
        "Genau's across the family")


def test_a_corner_control_reports_its_state_hollow_or_filled(qtbot):
    unfavorited = _corner_image(icons.corner_star_icon(favorite=False, armed=False))
    assert unfavorited.pixelColor(24, 25).alpha() < 32
    open_plus = _corner_image(icons.corner_enhance_icon(icons.ENHANCE_OPEN,
                                                        armed=False))
    assert open_plus.pixelColor(24, 24).alpha() < 32


def test_an_image_that_can_take_another_enhancement_shows_both_at_once(qtbot):
    more = _corner_image(icons.corner_enhance_icon(icons.ENHANCE_MORE, armed=False))
    assert more.pixelColor(24, 24).alpha() < 32, (
        "the clear cuts only the icon's own pixmap, where the shadow is all that lies under the "
        "plus, so the button's ground shows through the hollow")
    yellows = [
        (x, y)
        for y in range(48) for x in range(48)
        if more.pixelColor(x, y) == YELLOW
    ]
    assert yellows, "the enhancement it already holds never showed"
    assert max(x for x, _y in yellows) > 24 + 12
    assert max(y for _x, y in yellows) > 24 + 12


def test_arming_a_corner_button_changes_its_icon(qtbot):
    rest = _corner_image(icons.corner_trash_icon(armed=False))
    armed = _corner_image(icons.corner_trash_icon(armed=True))
    assert rest != armed
    assert any(armed.pixelColor(x, y) == RED
               for y in range(48) for x in range(48))
    star_rest = _corner_image(icons.corner_star_icon(favorite=False, armed=False))
    star_armed = _corner_image(icons.corner_star_icon(favorite=False, armed=True))
    assert star_rest != star_armed


def test_a_spent_enhance_corner_keeps_its_look_when_it_is_disabled(qtbot):
    icon = icons.corner_enhance_icon(icons.ENHANCE_HELD, armed=False)
    normal = icon.pixmap(QSize(48, 48), QIcon.Mode.Normal).toImage()
    disabled = icon.pixmap(QSize(48, 48), QIcon.Mode.Disabled).toImage()
    assert normal == disabled


def test_a_favorite_folders_favorite_is_the_same_green(qtbot):
    filled = icons.star_icon(filled=True).pixmap(QSize(48, 48), QIcon.Mode.Normal)
    assert filled.toImage().pixelColor(24, 25) == GREEN
    outline = icons.star_icon(filled=False)
    assert outline.pixmap(QSize(48, 48), QIcon.Mode.Normal).toImage() \
        != filled.toImage()


def test_reroll_seed_icons_render_and_differ_by_media(qtbot):
    video = icons.reroll_seed_icon(MediaType.VIDEO)
    image = icons.reroll_seed_icon(MediaType.IMAGE)
    size = QSize(24, 24)
    assert not video.pixmap(size).isNull()
    assert not image.pixmap(size).isNull()
    assert video.pixmap(size).toImage() != image.pixmap(size).toImage()


def test_gallery_pane_button_icons_render_with_normal_and_disabled_modes(qtbot):
    makers = (icons.back_icon, icons.forward_icon, icons.undo_icon, icons.redo_icon,
              icons.delete_icon, icons.latest_icon, icons.radio_icon,
              icons.populate_icon, icons.slideshow_icon, icons.enhance_icon,
              icons.custom_collection_icon,
              lambda: icons.star_icon(filled=True), lambda: icons.star_icon(filled=False))
    for make in makers:
        icon = make()
        assert not icon.isNull()
        size = QSize(24, 24)
        assert not icon.pixmap(size, QIcon.Mode.Normal).isNull()
        assert not icon.pixmap(size, QIcon.Mode.Disabled).isNull()


def test_the_bank_glyphs_are_all_different_marks(qtbot):
    size = QSize(24, 24)
    drawn = {
        name: make().pixmap(size).toImage()
        for name, make in (
            ("back", icons.back_icon), ("forward", icons.forward_icon),
            ("undo", icons.undo_icon), ("redo", icons.redo_icon),
            ("populate", icons.populate_icon), ("slideshow", icons.slideshow_icon),
            ("enhance", icons.enhance_icon), ("delete", icons.delete_icon),
            ("radio", icons.radio_icon),
            ("group", icons.custom_collection_icon),
            ("star", lambda: icons.star_icon(filled=True)),
        )
    }
    names = sorted(drawn)
    for i, first in enumerate(names):
        for second in names[i + 1:]:
            assert drawn[first] != drawn[second], f"{first} and {second} draw alike"


def test_undo_and_redo_carry_their_heads_on_opposite_sides(qtbot):
    size = QSize(48, 48)
    undo_left, undo_right = _top_corner_ink(icons.undo_icon().pixmap(size))
    redo_left, redo_right = _top_corner_ink(icons.redo_icon().pixmap(size))
    assert undo_left > undo_right * 1.5
    assert redo_right > redo_left * 1.5


def _top_corner_ink(pixmap) -> tuple[int, int]:
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
    size = QSize(48, 48)
    for icon, color in ((icons.star_icon(filled=True), GREEN),
                        (icons.enhance_icon(), YELLOW),
                        (icons.delete_icon(), RED)):
        assert _dominant_color(icon.pixmap(size, QIcon.Mode.Normal)) == color.rgb()
        muted = _dominant_color(icon.pixmap(size, QIcon.Mode.Disabled))
        assert muted == TEXT_MUTED.rgb()


def _dominant_color(pixmap) -> int:
    image = pixmap.toImage()
    counts = Counter(
        image.pixel(x, y)
        for y in range(image.height()) for x in range(image.width())
        if image.pixelColor(x, y).alpha() == 255
    )
    return counts.most_common(1)[0][0]


def test_experiment_icons_render_and_verdicts_differ(qtbot):
    flask = icons.flask_icon()
    size = QSize(24, 24)
    assert not flask.pixmap(size, QIcon.Mode.Normal).isNull()
    assert not flask.pixmap(size, QIcon.Mode.Disabled).isNull()
    keep = icons.experiment_verdict_icon("up")
    reject = icons.experiment_verdict_icon("down")
    assert not keep.pixmap(size).isNull()
    assert not reject.pixmap(size).isNull()
    assert keep.pixmap(size).toImage() != reject.pixmap(size).toImage()


def test_every_gallery_pane_button_mark_is_the_familys_shared_glyph(qtbot):
    cases = (
        (icons.back_icon(), "chevron_left", TEXT_PRIMARY),
        (icons.forward_icon(), "chevron_right", TEXT_PRIMARY),
        (icons.undo_icon(), "undo_arrow", TEXT_PRIMARY),
        (icons.redo_icon(), "redo_arrow", TEXT_PRIMARY),
        (icons.populate_icon(), "bolt", TEXT_PRIMARY),
        (icons.shield_icon(), "shield", TEXT_PRIMARY),
        (icons.slideshow_icon(), "slideshow", TEXT_PRIMARY),
        (icons.enhance_icon(), "plus", YELLOW),
        (icons.mic_icon(), "mic", TEXT_PRIMARY),
        (icons.radio_icon(), "speaker", TEXT_PRIMARY),
        (icons.trash_icon(), "trash", TEXT_PRIMARY),
        (icons.delete_icon(), "trash", RED),
        (icons.star_icon(filled=True), "star", GREEN),
        (icons.star_icon(filled=False), "star_outline", TEXT_PRIMARY),
        (icons.latest_icon(), "latest", TEXT_PRIMARY),
        (icons.flask_icon(), "flask", TEXT_PRIMARY),
        (icons.custom_collection_icon(), "folder", TEXT_PRIMARY),
        (icons.all_icon(), "database", TEXT_PRIMARY),
    )
    for icon, name, color in cases:
        drawn = icon.pixmap(QSize(48, 48), QIcon.Mode.Normal).toImage()
        assert drawn == icon_pixmap(name, 48, color).toImage(), name


def test_the_tile_hover_controls_wear_shared_marks_too(qtbot):
    white = QColor(255, 255, 255)
    for icon, name in ((icons.experiment_verdict_icon("up"), "check"),
                       (icons.experiment_verdict_icon("down"), "cross")):
        drawn = icon.pixmap(QSize(48, 48)).toImage()
        assert drawn == icon_pixmap(name, 48, white).toImage(), name


_MARK_ARGUMENT = {"qt_icon": 0, "icon_pixmap": 0, "shapes_of": 0, "shared_icon": 0,
                  "draw_icon": 1}


def _names_in(argument):
    if isinstance(argument, ast.Constant) and isinstance(argument.value, str):
        yield argument.value
    elif isinstance(argument, ast.IfExp):
        yield from _names_in(argument.body)
        yield from _names_in(argument.orelse)


def test_every_mark_this_app_names_is_one_its_shared_ui_draws_since_a_missing_one_is_silently_stood_in_for():
    named = set()
    for path in Path(origenerator.__file__).parent.rglob("*.py"):
        for call in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if not isinstance(call, ast.Call):
                continue
            position = _MARK_ARGUMENT.get(getattr(call.func, "id", None)
                                          or getattr(call.func, "attr", None))
            if position is None or len(call.args) <= position:
                continue
            named |= set(_names_in(call.args[position]))

    assert "trash" in named
    assert named - set(icon_names()) == set()

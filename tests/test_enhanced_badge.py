from origenerator.gui.thumbnail_widget import ThumbnailWidget


def test_enhanced_tile_wears_the_yellow_plus_badge(qtbot):
    # An enhanced image's tile carries the corner badge; a plain tile grows
    # none at all, so an unenhanced thumbnail stays clean.
    enhanced = ThumbnailWidget("p1", None, "seed 1", enhanced=True)
    qtbot.addWidget(enhanced)
    assert enhanced._enhanced_badge is not None

    plain = ThumbnailWidget("p2", None, "seed 2")
    qtbot.addWidget(plain)
    assert plain._enhanced_badge is None


def test_enhanced_badge_sits_clear_of_the_other_corners(qtbot):
    # Bottom-right of the image area: the media badge and re-roll controls own
    # the top-left, the star the top-right — all four can coexist on one tile.
    tile = ThumbnailWidget("p1", None, "seed 1", enhanced=True, starred=True,
                           media_type="image")
    qtbot.addWidget(tile)
    badge = tile._enhanced_badge
    assert badge.x() > tile.width() // 2          # right half...
    assert badge.y() > tile.height() // 2         # ...lower half (image bottom)
    star = tile._star_badge
    assert badge.geometry().intersected(star.geometry()).isEmpty()

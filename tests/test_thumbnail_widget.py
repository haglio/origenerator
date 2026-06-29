from origenerator.gui.thumbnail_widget import (
    ThumbnailWidget, _BORDER_SELECTED, _BORDER_UNSELECTED,
)


def test_thumbnail_starts_unselected(qtbot):
    tw = ThumbnailWidget("p1", None, "label")
    qtbot.addWidget(tw)
    assert tw.is_selected() is False
    assert _BORDER_UNSELECTED in tw._image_label.styleSheet()


def test_set_selected_highlights_the_image_border(qtbot):
    tw = ThumbnailWidget("p1", None, "label")
    qtbot.addWidget(tw)

    tw.set_selected(True)
    assert tw.is_selected() is True
    # The cue lives on the image QLabel — which actually paints a stylesheet
    # border — not the tile QWidget, which would render nothing.
    assert _BORDER_SELECTED in tw._image_label.styleSheet()
    assert tw.styleSheet() == ""

    tw.set_selected(False)
    assert tw.is_selected() is False
    assert _BORDER_SELECTED not in tw._image_label.styleSheet()
    assert _BORDER_UNSELECTED in tw._image_label.styleSheet()

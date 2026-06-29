from origenerator.gui.thumbnail_widget import ThumbnailWidget, _SELECTED_BG


def test_thumbnail_starts_unselected(qtbot):
    tw = ThumbnailWidget("p1", None, "label")
    qtbot.addWidget(tw)
    assert tw.is_selected() is False
    assert tw.styleSheet() == ""  # no selection fill at rest


def test_set_selected_fills_the_whole_tile_background(qtbot):
    tw = ThumbnailWidget("p1", None, "label")
    qtbot.addWidget(tw)

    tw.set_selected(True)
    assert tw.is_selected() is True
    # The whole tile — behind both the image and the caption — gets the fill.
    assert "background-color" in tw.styleSheet()
    assert _SELECTED_BG in tw.styleSheet()

    tw.set_selected(False)
    assert tw.is_selected() is False
    assert tw.styleSheet() == ""

from origenerator.gui.thumbnail_widget import ThumbnailWidget


def test_thumbnail_starts_unselected(qtbot):
    tw = ThumbnailWidget("p1", None, "label")
    qtbot.addWidget(tw)
    assert tw.is_selected() is False


def test_set_selected_toggles_the_highlight(qtbot):
    tw = ThumbnailWidget("p1", None, "label")
    qtbot.addWidget(tw)

    tw.set_selected(True)
    assert tw.is_selected() is True
    highlighted = tw.styleSheet()
    assert "#3d7eff" in highlighted  # the selection accent is visible

    tw.set_selected(False)
    assert tw.is_selected() is False
    assert "#3d7eff" not in tw.styleSheet()

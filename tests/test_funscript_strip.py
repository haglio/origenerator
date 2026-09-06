from PyQt6.QtGui import QColor

from origenerator.funscript import synthesize_actions
from origenerator.gui.funscript_strip import FunscriptStrip


def test_strip_is_a_thin_fixed_height_bar(qtbot):
    strip = FunscriptStrip()
    qtbot.addWidget(strip)
    assert 0 < strip.height() <= 24
    assert strip.minimumHeight() == strip.maximumHeight()  # fixed, doesn't grow


def test_paints_without_error_scripted_and_empty(qtbot):
    # grab() forces a paint into a pixmap — a smoke test that paintEvent runs for
    # both a scripted strip (heatmap) and an empty one (inert bar).
    strip = FunscriptStrip()
    qtbot.addWidget(strip)
    strip.resize(120, strip.height())

    strip.set_actions(synthesize_actions(3.0, hz=1.2, loop=False))
    assert not strip.grab().isNull()

    strip.set_actions([])
    assert not strip.grab().isNull()


def test_the_playhead_marks_how_far_into_the_script_playback_is(qtbot):
    # A white line at the fraction of the strip playback has reached, on the
    # same time axis the heatmap is drawn on, so a clip's length can be read
    # off the strip while it plays.
    strip = FunscriptStrip()
    qtbot.addWidget(strip)
    strip.resize(100, strip.height())
    actions = synthesize_actions(4.0, hz=1.0, loop=False)
    strip.set_actions(actions)
    strip.set_playhead(actions[-1]["at"] // 2)
    image = strip.grab().toImage()
    y = strip.height() // 2
    white = QColor(255, 255, 255)
    assert image.pixelColor(50, y) == white
    assert image.pixelColor(25, y) != white and image.pixelColor(75, y) != white
    assert strip._playhead == actions[-1]["at"] // 2


def test_a_new_script_starts_with_no_playhead(qtbot):
    strip = FunscriptStrip()
    qtbot.addWidget(strip)
    strip.resize(100, strip.height())
    strip.set_actions(synthesize_actions(4.0, hz=1.0, loop=False))
    strip.set_playhead(1000)
    strip.set_actions(synthesize_actions(2.0, hz=1.0, loop=False))
    assert strip._playhead is None
    image = strip.grab().toImage()
    y = strip.height() // 2
    assert all(image.pixelColor(x, y) != QColor(255, 255, 255) for x in range(100))

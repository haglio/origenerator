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

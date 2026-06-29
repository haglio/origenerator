"""The custom CheckBox must paint a real ticked box, not the native dark
style's bare chevron (which reads as a down-caret).

These render the widget and sample pixels in the indicator region: a checked
box is a white tick on a filled accent square; an unchecked box is an empty
dark square with no tick.
"""

from PyQt6.QtGui import QColor

from origenerator.gui.check_box import CheckBox, _BOX
from shared_ui.colors import BLUE


def _classify(cb):
    """Render the checkbox and tally indicator-region pixels by kind."""
    img = cb.grab().toImage()
    blue = white = dark = 0
    for x in range(0, _BOX + 3):
        for y in range(cb.height()):
            c = QColor(img.pixel(x, y))
            r, g, b = c.red(), c.green(), c.blue()
            if abs(r - BLUE.red()) < 50 and abs(g - BLUE.green()) < 50 and abs(b - BLUE.blue()) < 50:
                blue += 1
            elif r > 200 and g > 200 and b > 200:
                white += 1
            elif r < 80 and g < 80 and b < 80:
                dark += 1
    return blue, white, dark


def test_checked_draws_white_tick_on_filled_box(qtbot):
    cb = CheckBox("Random")
    qtbot.addWidget(cb)
    cb.setChecked(True)
    cb.resize(140, 24)
    blue, white, _ = _classify(cb)
    # A solid accent fill...
    assert blue > 30
    # ...with a light check mark stroked over it.
    assert white > 4


def test_unchecked_draws_empty_box_no_tick(qtbot):
    cb = CheckBox("Random")
    qtbot.addWidget(cb)
    cb.setChecked(False)
    cb.resize(140, 24)
    blue, white, dark = _classify(cb)
    assert blue == 0          # no accent fill
    assert white == 0         # no tick
    assert dark > 30          # an empty dark box


def test_click_toggles_checked_state(qtbot):
    cb = CheckBox("Random")
    qtbot.addWidget(cb)
    cb.show()
    assert cb.isChecked() is False
    cb.click()
    assert cb.isChecked() is True

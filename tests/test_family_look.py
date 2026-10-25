"""Origenerator wears the family's look: shared_ui's colors, marks, lettering and spacing, none of its own."""
from __future__ import annotations

from pathlib import Path

import pytest
from shared_ui.look_guard import assert_the_look_is_shared_uis

pytestmark = pytest.mark.repo_check

_CHECKOUT = Path(__file__).resolve().parents[1]

# Not a look: the gray the motion aimer's pose model was trained to see past the
# edges of an image, so it pads every image with that gray before asking it.
_THE_POSE_MODELS_LETTERBOX = "origenerator/workflows/motion_aim.py: color (114, 114, 114)"
# Not ours to set: the gap Qt's own tab layout puts between a tab's mark and its label.
_QTS_TAB_LABEL_GAP = "origenerator/gui/eliding_tab_bar.py: spacing _QT_LABEL_GAP = 4"
# Not drawn: how far below the pane's top a revealed tile is scrolled to.
_A_REVEALS_SCROLL = "origenerator/gui/pane_place.py: spacing REVEAL_MARGIN = 40"
# Not lettering: the brackets round a combination are as tall as the halves they hold.
_THE_BRACKETS_ROUND_A_COMBINATION = ("origenerator/gui/combination.py: text size "
                                     "enclosing.setPixelSize(max(1, int(side * _PAREN_HEIGHT_SHARE)))")
# Artwork: the app icon's corner on its 256px canvas, which shared_ui.app_icon's spec checks.
_THE_APP_ICONS_CORNER = "origenerator/icon_design.py: spacing CORNER_RADIUS = 5"


def test_everything_origenerator_draws_with_comes_from_shared_ui():
    assert_the_look_is_shared_uis(_CHECKOUT, [_CHECKOUT / "origenerator", _CHECKOUT / "tools"],
                                  allowing=(_THE_POSE_MODELS_LETTERBOX, _QTS_TAB_LABEL_GAP, _A_REVEALS_SCROLL,
                                            _THE_BRACKETS_ROUND_A_COMBINATION, _THE_APP_ICONS_CORNER))

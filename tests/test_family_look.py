"""Origenerator wears the family's look: shared_ui's colors and marks, none of its own."""
from __future__ import annotations

from pathlib import Path

from shared_ui.look_guard import assert_the_look_is_shared_uis

_CHECKOUT = Path(__file__).resolve().parents[1]

# Not a look: the gray the motion aimer's pose model was trained to see past the
# edges of a picture, so it pads every picture with that gray before asking it.
_THE_POSE_MODELS_LETTERBOX = "origenerator/workflows/motion_aim.py: color (114, 114, 114)"


def test_every_color_and_mark_origenerator_draws_comes_from_shared_ui():
    assert_the_look_is_shared_uis(_CHECKOUT, [_CHECKOUT / "origenerator", _CHECKOUT / "tools"],
                                  allowing=(_THE_POSE_MODELS_LETTERBOX,))

"""The shared "already generated" dialog: which seed(s) it offers to re-roll."""

from origenerator.gui.reroll_prompt import (
    REROLL_BOTH,
    REROLL_IMAGE,
    REROLL_VIDEO,
    _build_reroll_box,
)
from origenerator.workflows import WORKFLOW_REGISTRY

_I2V = WORKFLOW_REGISTRY["wan22_i2v"]
_SDXL = WORKFLOW_REGISTRY["sdxl_t2i"]


def _labels(mapping):
    return {button.text(): choice for button, choice in mapping.items()}


def test_offers_the_two_seed_choice_when_the_frame_is_rebuildable(qtbot):
    # An i2v whose start frame is a re-buildable generation can re-roll either
    # seed on its own, or both.
    _box, mapping = _build_reroll_box(None, _I2V, can_reroll_image=True)
    assert _labels(mapping) == {
        "New Video Seed": REROLL_VIDEO,
        "New Image Seed": REROLL_IMAGE,
        "New Both Seeds": REROLL_BOTH,
    }


def test_offers_a_single_seed_choice_otherwise(qtbot):
    # A plain workflow (or an i2v on a hand-picked frame) has only one seed to
    # re-roll — the old single "New Random Seed" button.
    _box, mapping = _build_reroll_box(None, _SDXL, can_reroll_image=False)
    assert _labels(mapping) == {"New Random Seed": REROLL_VIDEO}

from __future__ import annotations

from origenerator.config import PROJECT_DIR
from origenerator.icon_design import render_icon
from PIL import Image
from shared_ui.app_icon import CANVAS, assert_follows_the_family_spec

ICON_PATH = PROJECT_DIR / "icon.ico"


def test_the_icon_is_the_familys_o():
    assert_follows_the_family_spec(ICON_PATH, "O")


def test_committed_icon_matches_the_generator(qapp):
    master = Image.open(ICON_PATH).convert("RGBA")
    assert master.size == (CANVAS, CANVAS)
    assert master.tobytes() == render_icon(CANVAS).tobytes()

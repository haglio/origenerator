"""The app icon follows the family's icon spec, and is what icon_design renders."""

from PIL import Image
from shared_ui.app_icon import CANVAS, assert_follows_the_family_spec

from origenerator.config import PROJECT_DIR
from origenerator.icon_design import render_icon

ICON_PATH = PROJECT_DIR / "icon.ico"


def test_the_icon_is_the_familys_o():
    # One PINK block letter on the family's 5x5 grid, checked the way every
    # app's is.  The spec used to live in this file alone, naming the other
    # apps' letters and checking only this one.
    assert_follows_the_family_spec(ICON_PATH, "O")


def test_committed_icon_matches_the_generator(qapp):
    # The shipped icon.ico must be exactly what icon_design renders, so the
    # asset can never silently drift from the design module that defines it.
    master = Image.open(ICON_PATH).convert("RGBA")
    assert master.size == (CANVAS, CANVAS)
    assert master.tobytes() == render_icon(CANVAS).tobytes()

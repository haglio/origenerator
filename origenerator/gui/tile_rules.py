from __future__ import annotations

from shared_ui.palette import BLACK, BLUE, WHITE, as_hex, as_rgba
from shared_ui.spacing import BUTTON_RADIUS

from origenerator.gui import palette

SELECTED = "selected"
ITEM_TILE = "thumbnailTile"
THUMBNAIL = "tileThumbnail"
CAPTION = "tileCaption"
SEED_BUTTON = "tileSeedButton"
CORNER_FACE = "cornerButtonFace"
STATUS_SCRIM = "tileStatusScrim"


def _on_the_ground(selector: str) -> str:
    return (f"{selector} {{ background: {as_rgba(BLACK, 0.55)}; border: none; "
            f"border-radius: {BUTTON_RADIUS}px; }}")


def tile_rules() -> str:
    return (
        f'#{ITEM_TILE}[{SELECTED}="true"] {{ background-color: {palette.SELECTED_FILL}; '
        f"border-radius: {BUTTON_RADIUS}px; }}"
        f"QLabel#{THUMBNAIL} {{ background-color: transparent; "
        f"border: 2px solid {palette.TILE_BORDER}; border-radius: {BUTTON_RADIUS}px; }}"
        f'QLabel#{THUMBNAIL}[{SELECTED}="true"] {{ border-color: {palette.SELECTED_BORDER}; }}'
        f"QLabel#{CAPTION} {{ background-color: transparent; }}"
        + _on_the_ground(f"QPushButton#{CORNER_FACE}")
        + _on_the_ground(f"QPushButton#{SEED_BUTTON}")
        + f"QPushButton#{SEED_BUTTON}:hover {{ background: {as_rgba(BLUE, 0.9)}; }}"
        f"QLabel#{STATUS_SCRIM} {{ background-color: {as_rgba(BLACK, 0.45)}; "
        f"color: {as_hex(WHITE)}; font-weight: bold; border-radius: {BUTTON_RADIUS}px; }}"
    )

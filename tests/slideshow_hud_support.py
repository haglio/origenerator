from __future__ import annotations

from funestra.hud_overlay import HUD_OVERLAY_ID
from funestra.scrubber_bar import SCRUBBER_HEIGHT
from funestra.testing import FakeEngine
from funestra.volume import VOLUME_CONTROL_H, volume_control_xy
from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QKeyEvent

from origenerator.fun_time_mode import SHAPES
from tests.own_funestra_support import VIEWPORT


def open_both_shapes(gallery_or_director) -> None:
    for shape in SHAPES:
        gallery_or_director.fill_the_region(shape)


def shown_of(slideshow):
    return slideshow.shown if hasattr(slideshow, "shown") else slideshow


def program_of(slideshow):
    shown = shown_of(slideshow)
    return shown.program if hasattr(shown, "program") else shown._program


def funestra_of(slideshow):
    program = program_of(slideshow)
    program.open_if_it_has_a_list()
    return program.funestra


def engine_of(slideshow) -> FakeEngine:
    return program_of(slideshow).engine


def tick_the_funestra(slideshow) -> None:
    shown = shown_of(slideshow)
    program_of(slideshow).tick()
    asks = shown.asks if hasattr(shown, "asks") else shown._asks
    asks.read_now()


def hud_targets(slideshow):
    funestra = funestra_of(slideshow)
    program_of(slideshow).tick()
    return funestra._hud.targets


def hud_button_names(slideshow) -> list[str]:
    return [button.command.removeprefix(f"{shown_of(slideshow).hud_shape}_")
            for _rect, button in hud_targets(slideshow).buttons]


def _on_screen(slideshow, rect) -> tuple[int, int]:
    left, top, _pixels = engine_of(slideshow).overlays[HUD_OVERLAY_ID]
    x, y, width, height = rect
    return round(left + x + width / 2), round(top + y + height / 2)


def button_on_screen(slideshow, command) -> tuple[int, int]:
    rect, = [rect for rect, button in hud_targets(slideshow).buttons if button.command == command]
    return _on_screen(slideshow, rect)


def thumbnail_on_screen(slideshow, path) -> tuple[int, int]:
    rect, = [rect for rect, target in hud_targets(slideshow).click if target == path]
    return _on_screen(slideshow, rect)


def speaker_on_screen(slideshow) -> tuple[int, int]:
    left, top, _pixels = engine_of(slideshow).overlays[HUD_OVERLAY_ID]
    x, y, width, height = funestra_of(slideshow)._hud.row.rect
    cx, cy = volume_control_xy(viewport_w=width, viewport_h=height, timeline_h=SCRUBBER_HEIGHT)
    return round(left + x + cx + 4), round(top + y + cy + VOLUME_CONTROL_H // 2)


def click(slideshow, at: tuple[int, int], *, again: bool = False) -> None:
    funestra = funestra_of(slideshow)
    (funestra.press_again if again else funestra.press)(*at, viewport=VIEWPORT)
    funestra.release()
    tick_the_funestra(slideshow)


def double_click(slideshow, at: tuple[int, int]) -> None:
    click(slideshow, at)
    click(slideshow, at, again=True)


def press_key_on(slideshow, key) -> None:
    shown_of(slideshow).take_key(QKeyEvent(QEvent.Type.KeyPress, key, Qt.KeyboardModifier.NoModifier))

"""The generation queue, painted onto the one panel a show wears.

A show covers the lower strip that carries the queue, and it is the worst
moment to lose it: the line deliberately stops moving there (every video in it
is held until the show closes, :mod:`origenerator.queue_line`) and it is when
the user keeps adding to it.  So it rides on the panel the show already wears
rather than on a plate of its own, which would be a second HUD.

It says what the strip says: the job being made with its live frame and the
clock across its bar, then each waiting job as a row -- the button that throws
it away, the picture it is made from, and what it costs.  They go back as the
panel's own declared buttons (:class:`player_core.hud_button.Button`), so it
presses and names them exactly as it presses its own.
"""
from __future__ import annotations

import io
import os
from dataclasses import dataclass
from functools import cache

from PIL import Image, ImageDraw
from player_core.hud_button import Button
from player_core.hud_panel import (
    SYMBOL_FONT,
    draw_button,
    fit_text,
    load_font,
    text_width,
)
from player_core.satellite_hud import BLOCK_GAP, CTRL_BTN, MAP_THUMB_H
from shared_ui.palette import (
    BLUE,
    BLUE_LIGHT,
    BORDER_SUBTLE,
    TEXT_MUTED,
    TEXT_PRIMARY,
)

from origenerator.gui.inflight import (
    discard_run_text,
    discard_run_tooltip,
    foreign_queue_text,
    held_row_text,
    queue_held_text,
    queue_lead_text,
    queue_lead_tooltip,
    queue_wait_text,
    starting_row_text,
)
from origenerator.gui.queue_thumbs import FOLDER_CELLS
from origenerator.workflows.derived_size import resolve_input_image_path

# What a press on this block posts, and what the show does with each: throw the
# job away, go to the folder it will land in, drop another app's work.
CANCEL = "queue_cancel"
OPEN = "queue_open"
CLEAR = "queue_clear"
# The head's picture goes where its row goes, and says so under its own verb:
# it is a picture of the job being made, not a row that can be dragged anywhere.
FRAME = "queue_frame"

CLEAR_WORD = "Clear"
FRAME_TOOLTIP = "Open the folder this run will land in"

# How many rows the block draws at once. The strip opens about this tall in the
# main window, and a line longer than this is scrolled through rather than drawn
# whole: a panel that grew a row per queued job would run off the screen the
# first time a folder-wide request filled it.
ROWS = 4

_TINY_PT = 8            # the panel's own small face, as its own painters size it
_WORD_PAD = 6           # the room a word button keeps either side of its word
_GAP = 6                # between the things on one row
_ROW_H = CTRL_BTN + BLOCK_GAP
_BAR_H = CTRL_BTN
_BAR_PAD = 6            # the clock's breathing room at each end of its bar
_BAND_H = 4             # the pass band along the bar's foot
_RADIUS = 3             # the family's own button corner, which the bar shares
_CELL = CTRL_BTN        # one picture cell on a row
_CELL_GAP = 1
_BLOCK_W = FOLDER_CELLS * _CELL + (FOLDER_CELLS - 1) * _CELL_GAP
# The head's picture: a map cell's own height, so the run being made is worth
# looking at beside the bar measuring it and the two blocks read at one scale.
_FRAME = MAP_THUMB_H
_PLUS_W = 10            # the operator between a start frame and its recipe
_PAREN_W = 5            # the marks around a recipe whose prompt was edited
_MARK_H = 8             # the slot the "…" takes when the line runs on past the rows
_MARK_DOT = 1
_MARK_GAP = 4
_DROP_W = 2             # the mark showing where a dragged row would land
# The widest the block asks the panel to be. Past this the texts elide instead:
# the panel is anchored in a corner of the screen, and a line of queued work is
# not worth half the width of a show.
_MAX_W = 460

_SLOT_ALPHA = 110       # a cell with nothing in it reads as a slot, not a picture


@cache
def _tiny():
    return load_font(_TINY_PT)


@cache
def _glyphs():
    return load_font(_TINY_PT, SYMBOL_FONT)


def _line_height() -> int:
    return sum(_tiny().getmetrics())


def _word_width(word: str) -> int:
    return text_width(_tiny(), word) + 2 * _WORD_PAD


def _on(rect, pointer) -> bool:
    if pointer is None:
        return False
    x, y, width, height = rect
    return x <= pointer[0] < x + width and y <= pointer[1] < y + height


@dataclass(frozen=True)
class JobLine:
    """One job in the line, as the panel draws it."""

    key: str
    lead: str
    note: str
    tooltip: str
    discard: str
    discard_tooltip: str
    movable: bool
    source: tuple[str | None, str | None]
    recipe_edited: bool
    folder: tuple[str, ...]


@dataclass(frozen=True)
class Leader:
    """The job ComfyUI is making, as the head of the block draws it."""

    key: str
    frame: bytes | None
    source: tuple[str | None, str | None]
    recipe_edited: bool
    caption: str
    compact: str
    progress: tuple[int, int] | None
    pass_progress: tuple[int, int] | None
    wait: str


@dataclass(frozen=True)
class QueueSection:
    """What is in flight, as the show's HUD draws it at the panel's foot."""

    lines: tuple[JobLine, ...] = ()
    leader: Leader | None = None
    idle_note: str = ""
    foreign: int = 0
    # Which row the drawn window opens on, and where a dragged row would land —
    # both the panel's own doing rather than the queue's, and both redrawn
    # through here because the block is painted, not laid out in widgets.
    first: int = 0
    drop_at: int | None = None


    @property
    def drawn(self) -> tuple[JobLine, ...]:
        """The rows the window opens on — the whole line, where it fits."""
        return self.lines[self.first:self.first + ROWS]

    @property
    def windowed(self) -> bool:
        return len(self.lines) > ROWS

    def size(self) -> tuple[int, int]:
        head_width, head_height = self._head_size()
        rows = self.drawn
        width = max([head_width] + [self._row_width(line) for line in rows])
        height = head_height
        if rows:
            height += BLOCK_GAP + len(rows) * _ROW_H
            if self.windowed:
                height += 2 * _MARK_H
        return min(width, _MAX_W), height

    def _head_size(self) -> tuple[int, int]:
        if self.leader is None:
            if not self.idle_note and not self.foreign:
                return 0, 0
            width = text_width(_tiny(), self.idle_note)
            if self.foreign:
                width += _GAP + _word_width(CLEAR_WORD)
            return width, max(_line_height(), CTRL_BTN if self.foreign else 0)
        bar = text_width(_tiny(), self.leader.caption) + 2 * _BAR_PAD
        column = max(bar, text_width(_tiny(), self.leader.wait))
        if self.foreign:
            column += _GAP + _word_width(CLEAR_WORD)
        return _FRAME + _GAP + column, _FRAME

    def _row_width(self, line: JobLine) -> int:
        width = _BLOCK_W + _GAP + text_width(_tiny(), line.lead)
        if line.discard:
            width += _word_width(line.discard) + _GAP
        if line.note:
            width += _GAP + text_width(_tiny(), line.note)
        return width


    def paint(self, image, x: int, y: int, width: int,
              pointer: tuple[int, int] | None) -> list[tuple[tuple, Button]]:
        draw = ImageDraw.Draw(image)
        targets: list[tuple[tuple, Button]] = []
        top = y
        head = self._head_size()[1]
        if head:
            self._paint_head(image, draw, x, top, width, pointer, targets)
            top += head + BLOCK_GAP
        if self.drawn:
            if self.windowed:
                self._paint_mark(draw, x, top, width, self.first > 0)
                top += _MARK_H
            self._paint_rows(image, draw, x, top, width, pointer, targets)
            if self.windowed:
                self._paint_mark(draw, x, top + len(self.drawn) * _ROW_H, width,
                                 self.first + ROWS < len(self.lines))
        return targets

    def _paint_head(self, image, draw, x, y, width, pointer, targets) -> None:
        column, room = x, width
        if self.leader is not None:
            frame_width = self._paint_frame(image, draw, x, y)
            rect = (x, y, frame_width, _FRAME)
            targets.append((rect, Button(f"{FRAME}|{self.leader.key}", "", FRAME_TOOLTIP)))
            column = x + frame_width + _GAP
            room = max(0, x + width - column)
        if self.foreign:
            room = max(0, room - _GAP - self._paint_clear(image, draw, x + width, y,
                                                          pointer, targets))
        if self.leader is not None:
            self._paint_bar(draw, column, y, room)
            if self.leader.wait:
                self._say(draw, column, y + _BAR_H + BLOCK_GAP + _line_height() / 2,
                          room, self.leader.wait)
            return
        if self.idle_note:
            self._say(draw, column, y + CTRL_BTN / 2, room, self.idle_note)

    def _paint_clear(self, image, draw, right, y, pointer, targets) -> int:
        word = _word_width(CLEAR_WORD)
        rect = (right - word, y, word, CTRL_BTN)
        button = Button(CLEAR, CLEAR_WORD, _clear_tooltip(self.foreign))
        draw_button(image, draw, rect, button, hovered=_on(rect, pointer),
                    glyph_font=_glyphs(), word_font=_tiny())
        targets.append((rect, button))
        return word

    def _say(self, draw, x, y, room, text) -> None:
        draw.text((x, y), fit_text(_tiny(), text, room), font=_tiny(),
                  anchor="lm", fill=(*TEXT_MUTED, 255))

    def _paint_bar(self, draw, x, y, width) -> None:
        """The clock, written across the bar it measures — the reading
        :class:`~origenerator.gui.progress_caption.ProgressCaption` draws in the
        strip, and empty rather than at nought for a run ComfyUI has not started."""
        leader = self.leader
        draw.rounded_rectangle([x, y, x + width - 1, y + _BAR_H - 1], radius=_RADIUS,
                               fill=(*BORDER_SUBTLE, 90), outline=(*BORDER_SUBTLE, 255))
        done = _fraction(leader.progress)
        if done:
            draw.rounded_rectangle([x, y, x + max(_RADIUS, int(width * done)) - 1,
                                    y + _BAR_H - 1], radius=_RADIUS, fill=(*BLUE, 255))
        band = _fraction(leader.pass_progress)
        if band is not None:
            foot = y + _BAR_H - 1 - _BAND_H
            draw.rectangle([x + 1, foot, x + width - 2, foot + _BAND_H - 1],
                           fill=(*BORDER_SUBTLE, 120))
            if band:
                draw.rectangle([x + 1, foot, x + 1 + int((width - 3) * band),
                                foot + _BAND_H - 1], fill=(*BLUE_LIGHT, 255))
        room = max(0, width - 2 * _BAR_PAD)
        caption = leader.caption
        if text_width(_tiny(), caption) > room:
            caption = leader.compact
        draw.text((x + width / 2, y + _BAR_H / 2), fit_text(_tiny(), caption, room),
                  font=_tiny(), anchor="mm", fill=(*TEXT_PRIMARY, 255))

    def _paint_frame(self, image, draw, x, y) -> int:
        """What is being made, or — until ComfyUI has streamed a frame of it —
        what it is being made from."""
        live = _frame_image(self.leader.frame, _FRAME)
        if live is not None:
            image.alpha_composite(live, (x, y + (_FRAME - live.height) // 2))
            return live.width
        return _paint_source(image, draw, x, y, _FRAME, self.leader.source,
                             self.leader.recipe_edited) or _slot(draw, x, y, _FRAME)

    def _paint_rows(self, image, draw, x, y, width, pointer, targets) -> None:
        for index, line in enumerate(self.drawn):
            row = y + index * _ROW_H
            cursor = x
            if line.discard:
                word = _word_width(line.discard)
                rect = (cursor, row, word, CTRL_BTN)
                button = Button(f"{CANCEL}|{line.key}", line.discard,
                                line.discard_tooltip, width=word)
                draw_button(image, draw, rect, button, hovered=_on(rect, pointer),
                            glyph_font=_glyphs(), word_font=_tiny())
                targets.append((rect, button))
                cursor += word + _GAP
            _paint_pictures(image, draw, cursor, row, line)
            cursor += _BLOCK_W + _GAP
            room = max(0, x + width - cursor)
            lead = fit_text(_tiny(), line.lead, room)
            draw.text((cursor, row + CTRL_BTN / 2), lead, font=_tiny(), anchor="lm",
                      fill=(*TEXT_PRIMARY, 255))
            if line.note:
                said = cursor + text_width(_tiny(), lead) + _GAP
                draw.text((said, row + CTRL_BTN / 2),
                          fit_text(_tiny(), line.note, max(0, x + width - said)),
                          font=_tiny(), anchor="lm", fill=(*TEXT_MUTED, 255))
            targets.append(((x, row, width, CTRL_BTN),
                            Button(f"{OPEN}|{line.key}", "", line.tooltip)))
        self._paint_drop(draw, x, y, width)

    def _paint_drop(self, draw, x, y, width) -> None:
        if self.drop_at is None:
            return
        slot = min(max(self.drop_at - self.first, 0), len(self.drawn))
        top = y + slot * _ROW_H - _DROP_W // 2
        draw.rectangle([x, top, x + width - 1, top + _DROP_W - 1], fill=(*BLUE, 255))

    def _paint_mark(self, draw, x, y, width, more: bool) -> None:
        """Three dots saying the line runs on past the rows drawn, as the map's
        own axes say it."""
        if not more:
            return
        middle_x, middle_y = x + width / 2, y + _MARK_H / 2
        for step in (-1, 0, 1):
            dot_x = middle_x + step * _MARK_GAP
            draw.ellipse([dot_x - _MARK_DOT, middle_y - _MARK_DOT,
                          dot_x + _MARK_DOT, middle_y + _MARK_DOT],
                         fill=(*TEXT_PRIMARY, 255))


def _clear_tooltip(foreign: int) -> str:
    return (f"Drop the {foreign} job{'' if foreign == 1 else 's'} another app has"
            " queued on ComfyUI")


def _fraction(progress) -> float | None:
    if not progress or progress[1] <= 0:
        return None
    return min(1.0, max(0.0, progress[0] / progress[1]))


def _slot(draw, x, y, side) -> int:
    """A cell with nothing in it: a faint square, so a row with no picture reads
    as a job whose picture has not arrived rather than as one that failed to draw."""
    draw.rectangle([x, y, x + side - 1, y + side - 1],
                   fill=(*BORDER_SUBTLE, _SLOT_ALPHA))
    return side


# (file, side, gray, written) -> the fitted cell, or None for a file that would
# not load. The block is repainted on every beat of the panel, and a start frame
# is a full-size render off disk.
_CELLS: dict[tuple[str, int, bool, int | None], Image.Image | None] = {}


def _written(path) -> int | None:
    try:
        return os.stat(path).st_mtime_ns
    except OSError:
        return None


def _cell(path, side: int, gray: bool = False) -> Image.Image | None:
    """``path`` fitted whole into a ``side`` square, or ``None`` if unreadable."""
    if not path:
        return None
    key = (str(path), side, gray, _written(path))
    if key not in _CELLS:
        _CELLS[key] = _fit(path, side, gray)
    return _CELLS[key]


def _fit(path, side: int, gray: bool) -> Image.Image | None:
    try:
        picture = Image.open(path).convert("RGBA")
    except (OSError, ValueError):
        return None
    if gray:
        picture = picture.convert("L").convert("RGBA")
    picture.thumbnail((side, side))
    cell = Image.new("RGBA", (side, side), (0, 0, 0, 0))
    cell.paste(picture, ((side - picture.width) // 2, (side - picture.height) // 2))
    return cell


def _frame_image(frame: bytes | None, side: int) -> Image.Image | None:
    """The latest live frame off ComfyUI, fitted into a ``side`` square."""
    if not frame:
        return None
    try:
        picture = Image.open(io.BytesIO(frame)).convert("RGBA")
    except (OSError, ValueError):
        return None
    picture.thumbnail((side, side))
    cell = Image.new("RGBA", (side, side), (0, 0, 0, 0))
    cell.paste(picture, ((side - picture.width) // 2, (side - picture.height) // 2))
    return cell


def _paint_source(image, draw, x, y, side, source, recipe_edited: bool) -> int:
    """A job's start frame and, where a combine brought one, the recipe clip it
    follows — gray, and in parentheses where its prompt was edited, as
    :mod:`origenerator.gui.combination_view` draws the same pair.  Nought when
    neither has anything to draw."""
    frame = _cell(source[0], side)
    recipe = _cell(source[1], side, gray=True)
    if frame is None and recipe is None:
        return 0
    cursor = x
    if frame is not None:
        image.alpha_composite(frame, (cursor, y))
        cursor += side
    if recipe is not None:
        if frame is not None:
            draw.text((cursor + _PLUS_W / 2, y + side / 2), "+", font=_tiny(),
                      anchor="mm", fill=(*TEXT_MUTED, 255))
            cursor += _PLUS_W
        if recipe_edited:
            draw.text((cursor + _PAREN_W / 2, y + side / 2), "(", font=_tiny(),
                      anchor="mm", fill=(*TEXT_MUTED, 255))
            cursor += _PAREN_W
        image.alpha_composite(recipe, (cursor, y))
        cursor += side
        if recipe_edited:
            draw.text((cursor + _PAREN_W / 2, y + side / 2), ")", font=_tiny(),
                      anchor="mm", fill=(*TEXT_MUTED, 255))
            cursor += _PAREN_W
    return cursor - x


def _paint_pictures(image, draw, x, y, line: JobLine) -> None:
    """A row's picture, as the strip draws the same one
    (:mod:`origenerator.gui.queue_thumbs`): what the job is made from, else what
    its folder holds."""
    if _paint_source(image, draw, x, y, _CELL, line.source, line.recipe_edited):
        return
    if not line.folder:
        return
    for index in range(FOLDER_CELLS):
        cell_x = x + index * (_CELL + _CELL_GAP)
        picture = _cell(line.folder[index], _CELL) if index < len(line.folder) else None
        if picture is None:
            _slot(draw, cell_x, y, _CELL)
        else:
            image.alpha_composite(picture, (cell_x, y))


def _line(item) -> JobLine:
    frame = resolve_input_image_path(item.source_image)
    return JobLine(
        key=item.key,
        lead=queue_lead_text(item),
        note=starting_row_text(item.starting) or held_row_text(item.held) or "",
        tooltip=f"{item.caption}\n\n{queue_lead_tooltip(item)}",
        discard=discard_run_text(item.auto_generating) if item.cancel is not None else "",
        discard_tooltip=discard_run_tooltip(item.auto_generating),
        movable=not item.reading.rendering,
        source=(str(frame) if frame is not None else None, item.recipe_thumbnail),
        recipe_edited=item.recipe_prompt_edited,
        folder=tuple(str(path) for path in item.folder_thumbnails[:FOLDER_CELLS]),
    )


def _leader(item) -> Leader:
    frame = resolve_input_image_path(item.source_image)
    return Leader(
        key=item.key,
        frame=item.reading.frame,
        source=(str(frame) if frame is not None else None, item.recipe_thumbnail),
        recipe_edited=item.recipe_prompt_edited,
        caption=item.reading.caption(),
        compact=item.reading.caption(compact=True),
        progress=item.reading.bars()[0],
        pass_progress=item.reading.bars()[1],
        wait=queue_wait_text(item.foreign_ahead) or "",
    )


def queue_section(items, foreign: int = 0, *, first: int = 0,
                  drop_at: int | None = None) -> QueueSection | None:
    """The block the panel hangs at its foot, or ``None`` with nothing to say.
    The head is whatever ComfyUI is making; with nothing of ours on the GPU it
    says why instead -- this show's own hold, else another app's backlog."""
    if not items and not foreign:
        return None
    leading = items[0] if items and not items[0].held else None
    idle = "" if leading is not None else (
        queue_held_text(sum(1 for item in items if item.held))
        or foreign_queue_text(foreign) or "")
    lines = tuple(_line(item) for item in items)
    return QueueSection(lines=lines,
                        leader=_leader(leading) if leading is not None else None,
                        idle_note=idle, foreign=foreign,
                        first=max(0, min(first, max(0, len(lines) - ROWS))),
                        drop_at=drop_at)

"""The generation queue, painted onto the one panel a slideshow wears.

A slideshow covers the lower strip that carries the queue, and it is the worst
moment to lose it: a slideshow is when the user keeps adding to it.  So it rides on
the panel the slideshow already wears rather than on a plate of its own, which would
be a second HUD.

It says what the strip says: the job being made with its live frame and the
clock across its bar, then each waiting job as a row -- its arrows, its shield,
its Cancel, the image it is made from, and what it costs.  They go as the
panel's own declared buttons (:class:`funestra.hud_button.Button`), so it
presses and names them exactly as it presses its own.
"""
from __future__ import annotations

import io
import os
from dataclasses import dataclass, field
from functools import cache

from funestra.hud_button import Button
from funestra.hud_marks import shared_mark
from funestra.hud_panel import (
    SYMBOL_FONT,
    draw_button,
    load_font,
    text_width,
)
from funestra.satellite_hud import BLOCK_GAP, CTRL_BTN, MAP_THUMB_H
from PIL import Image, ImageDraw
from shared_ui.icons_pil import paste_glyph
from shared_ui.lettering import fit_text
from shared_ui.palette import (
    BLUE,
    BLUE_LIGHT,
    BORDER_SUBTLE,
    TEXT_MUTED,
    TEXT_PRIMARY,
)
from shared_ui.spacing import BUTTON_PAD_H_TIGHT, BUTTON_RADIUS_HUD, GAP_MEDIUM, HAIRLINE
from shared_ui.type_scale import SIZE_TINY

from origenerator.gui.inflight import (
    CANCEL_TEXT,
    CLEAR_TEXT,
    MOVE_DOWN_TIP,
    MOVE_UP_TIP,
    SHIELD_TIP,
    START_NOW_TEXT,
    START_NOW_TOOLTIP,
    cancel_tooltip,
    clear_queue_tooltip,
    first_movable,
    foreign_queue_text,
    movable,
    queue_lead_text,
    queue_lead_tooltip,
    queue_wait_text,
    seconds_until_start,
    starting_row_text,
)
from origenerator.gui.queue_thumbs import FOLDER_CELLS
from origenerator.workflows.derived_size import resolve_input_image_path

# What a press on this block posts: move, shield or cancel a job, go to its
# folder, drop another app's work, start a video now.
UP = "queue_up"
DOWN = "queue_down"
SHIELD = "queue_shield"
CANCEL = "queue_cancel"
OPEN = "queue_open"
CLEAR = "queue_clear"
START_NOW = "queue_start_now"
# The head's thumbnail goes where its row goes, and says so under its own verb:
# it is a thumbnail of the job being made, not a row that can be dragged anywhere.
FRAME = "queue_frame"

FRAME_TOOLTIP = "Open the folder this run will land in"

# How many rows the block draws at once. The strip opens about this tall in the
# main window, and a line longer than this is scrolled through rather than drawn
# whole: a panel that grew a row per queued job would run off the screen the
# first time a folder-wide request filled it.
ROWS = 4
# How far a press on a row has to travel before it is a drag rather than the
# click that opens the job's folder.
_DRAG_START = 6

_WORD_PAD = BUTTON_PAD_H_TIGHT           # the room a word button keeps either side of its word
_GAP = GAP_MEDIUM                # between the things on one row
_ROW_H = CTRL_BTN + BLOCK_GAP
_BAR_H = CTRL_BTN
_BAR_PAD = GAP_MEDIUM            # the clock's breathing room at each end of its bar
_BAND_H = 4             # the pass band along the bar's foot
_CELL = CTRL_BTN        # one thumbnail cell on a row
_CELL_GAP = HAIRLINE
_BLOCK_W = FOLDER_CELLS * _CELL + (FOLDER_CELLS - 1) * _CELL_GAP
# The head's thumbnail: a map cell's own height, so the run being made is worth
# looking at beside the bar measuring it and the two blocks read at one scale.
_FRAME = MAP_THUMB_H
_PLUS_W = 10            # the operator between a start frame and its source video
_PAREN_W = 5            # the marks around a source video whose prompt was edited
_MARK_H = 8             # the slot the "…" takes when the line runs on past the rows
_MARK_SIDE = 12         # the frame the family's three dots are drawn in, as on the satellite's map
_DROP_W = 2             # the mark showing where a dragged row would land
# The widest the block asks the panel to be. Past this the texts elide instead:
# the panel is anchored in a corner of the screen, and a line of queued work is
# not worth half the width of a slideshow.
_MAX_W = 460

_SLOT_ALPHA = 110       # a cell with nothing in it reads as a slot, not a thumbnail


@cache
def _tiny():
    return load_font(SIZE_TINY)


@cache
def _glyphs():
    return load_font(SIZE_TINY, SYMBOL_FONT)


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
    cancelable: bool
    cancel_tooltip: str
    shieldable: bool
    shielded: bool
    can_move_up: bool
    can_move_down: bool
    source: tuple[str | None, str | None]
    prompt_edited: bool
    folder: tuple[str, ...]


@dataclass(frozen=True)
class Leader:
    """The job ComfyUI is making, as the head of the block draws it."""

    key: str
    frame: bytes | None
    source: tuple[str | None, str | None]
    prompt_edited: bool
    caption: str
    compact: str
    progress: tuple[int, int] | None
    pass_progress: tuple[int, int] | None
    wait: str
    start_now: bool = False


@dataclass(frozen=True)
class QueueSection:
    """What is in flight, as the slideshow's HUD draws it at the panel's foot."""

    lines: tuple[JobLine, ...] = ()
    leader: Leader | None = None
    foreign: int = 0
    # Which row the drawn window opens on, and where a dragged row would land —
    # both the panel's own doing rather than the queue's, and both redrawn
    # through here because the block is painted, not laid out in widgets.
    first: int = 0
    drop_at: int | None = None
    # The pointer on the block, told where each row and button was painted so
    # a press can be placed against them in the block's own pixels.
    pointer: QueuePointer | None = field(default=None, compare=False)

    @property
    def idle_note(self) -> str:
        if self.leader is not None:
            return ""
        return foreign_queue_text(self.foreign) or ""

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
            if not self.foreign:
                return 0, 0
            width = text_width(_tiny(), self.idle_note) + _GAP + _word_width(CLEAR_TEXT)
            return width, max(_line_height(), CTRL_BTN)
        bar = text_width(_tiny(), self.leader.caption) + 2 * _BAR_PAD
        under_the_bar = text_width(_tiny(), self.leader.wait)
        if self.leader.start_now:
            under_the_bar += _GAP + _word_width(START_NOW_TEXT)
        column = max(bar, under_the_bar)
        if self.foreign:
            column += _GAP + _word_width(CLEAR_TEXT)
        return _FRAME + _GAP + column, _FRAME

    def _row_width(self, line: JobLine) -> int:
        width = 2 * (CTRL_BTN + _GAP) + _BLOCK_W + _GAP + text_width(_tiny(), line.lead)
        if line.shieldable:
            width += CTRL_BTN + _GAP
        if line.cancelable:
            width += _word_width(CANCEL_TEXT) + _GAP
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
                self._paint_mark(image, x, top, width, self.first > 0)
                top += _MARK_H
            self._paint_rows(image, draw, x, top, width, pointer, targets)
            if self.windowed:
                self._paint_mark(image, x, top + len(self.drawn) * _ROW_H, width,
                                 self.first + ROWS < len(self.lines))
        if self.pointer is not None:
            self.pointer.painted(targets, (x, y))
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
            room = max(0, room - _GAP - self._paint_word(
                image, draw, column + room, y, pointer, targets,
                Button(CLEAR, CLEAR_TEXT, clear_queue_tooltip(self.foreign))))
        if self.leader is not None:
            self._paint_bar(draw, column, y, room)
            if self.leader.wait:
                middle = y + _BAR_H + BLOCK_GAP + _line_height() / 2
                said = self._say(draw, column, middle, room, self.leader.wait)
                if self.leader.start_now:
                    word = _word_width(START_NOW_TEXT)
                    self._paint_word(image, draw, column + said + _GAP + word,
                                     round(middle - CTRL_BTN / 2), pointer, targets,
                                     Button(START_NOW, START_NOW_TEXT, START_NOW_TOOLTIP))
            return
        if self.idle_note:
            self._say(draw, column, y + CTRL_BTN / 2, room, self.idle_note)

    def _paint_word(self, image, draw, right, y, pointer, targets, button) -> int:
        word = _word_width(button.glyph)
        _paint_button(image, draw, (right - word, y, word, CTRL_BTN), button, pointer, targets)
        return word

    def _say(self, draw, x, y, room, text) -> int:
        fitted = fit_text(_tiny(), text, room)
        draw.text((x, y), fitted, font=_tiny(), anchor="lm", fill=(*TEXT_MUTED, 255))
        return text_width(_tiny(), fitted)

    def _paint_bar(self, draw, x, y, width) -> None:
        """The clock, written across the bar it measures — the reading
        :class:`~origenerator.gui.progress_caption.ProgressCaption` draws in the
        strip, and empty rather than at nought for a run ComfyUI has not started."""
        leader = self.leader
        draw.rounded_rectangle([x, y, x + width - 1, y + _BAR_H - 1], radius=BUTTON_RADIUS_HUD,
                               fill=(*BORDER_SUBTLE, 90), outline=(*BORDER_SUBTLE, 255))
        done = _fraction(leader.progress)
        if done:
            draw.rounded_rectangle([x, y, x + max(BUTTON_RADIUS_HUD, int(width * done)) - 1,
                                    y + _BAR_H - 1], radius=BUTTON_RADIUS_HUD, fill=(*BLUE, 255))
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
                             self.leader.prompt_edited) or _slot(draw, x, y, _FRAME)

    def _paint_rows(self, image, draw, x, y, width, pointer, targets) -> None:
        for index, line in enumerate(self.drawn):
            row = y + index * _ROW_H
            cursor = x
            for verb, mark, tooltip, can_go in (
                    (UP, "chevron_up", MOVE_UP_TIP, line.can_move_up),
                    (DOWN, "chevron_down", MOVE_DOWN_TIP, line.can_move_down)):
                _paint_button(image, draw, (cursor, row, CTRL_BTN, CTRL_BTN),
                              Button(f"{verb}|{line.key}", shared_mark(mark), tooltip,
                                     width=CTRL_BTN, dim=not can_go),
                              pointer, targets)
                cursor += CTRL_BTN + _GAP
            if line.shieldable:
                _paint_button(image, draw, (cursor, row, CTRL_BTN, CTRL_BTN),
                              Button(f"{SHIELD}|{line.key}", shared_mark("shield"),
                                     SHIELD_TIP, width=CTRL_BTN, lit=line.shielded),
                              pointer, targets)
                cursor += CTRL_BTN + _GAP
            if line.cancelable:
                word = _word_width(CANCEL_TEXT)
                _paint_button(image, draw, (cursor, row, word, CTRL_BTN),
                              Button(f"{CANCEL}|{line.key}", CANCEL_TEXT,
                                     line.cancel_tooltip, width=word),
                              pointer, targets)
                cursor += word + _GAP
            _paint_thumbnails(image, draw, cursor, row, line)
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

    def _paint_mark(self, image, x, y, width, more: bool) -> None:
        """The family's three dots saying the line runs on past the rows drawn, as
        the map's own axes say it."""
        if not more:
            return
        middle_x, middle_y = x + width / 2, y + _MARK_H / 2
        paste_glyph(image, "more", (round(middle_x - _MARK_SIDE / 2), round(middle_y - _MARK_SIDE / 2),
                                    _MARK_SIDE, _MARK_SIDE), TEXT_PRIMARY)


def _paint_button(image, draw, rect, button, pointer, targets) -> None:
    draw_button(image, draw, rect, button, hovered=_on(rect, pointer),
                glyph_font=_glyphs(), word_font=_tiny())
    targets.append((rect, button))


def _fraction(progress) -> float | None:
    if not progress or progress[1] <= 0:
        return None
    return min(1.0, max(0.0, progress[0] / progress[1]))


def _slot(draw, x, y, side) -> int:
    """A cell with nothing in it: a faint square, so a row with no thumbnail reads
    as a job whose thumbnail has not arrived rather than as one that failed to draw."""
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
        opened = Image.open(path).convert("RGBA")
    except (OSError, ValueError):
        return None
    if gray:
        opened = opened.convert("L").convert("RGBA")
    opened.thumbnail((side, side))
    cell = Image.new("RGBA", (side, side), (0, 0, 0, 0))
    cell.paste(opened, ((side - opened.width) // 2, (side - opened.height) // 2))
    return cell


def _frame_image(frame: bytes | None, side: int) -> Image.Image | None:
    """The latest live frame off ComfyUI, fitted into a ``side`` square."""
    if not frame:
        return None
    try:
        opened = Image.open(io.BytesIO(frame)).convert("RGBA")
    except (OSError, ValueError):
        return None
    opened.thumbnail((side, side))
    cell = Image.new("RGBA", (side, side), (0, 0, 0, 0))
    cell.paste(opened, ((side - opened.width) // 2, (side - opened.height) // 2))
    return cell


def _paint_source(image, draw, x, y, side, source, prompt_edited: bool) -> int:
    """A job's start frame and, where a combine brought one, the source video it
    follows — gray, and in parentheses where its prompt was edited, as
    :mod:`origenerator.gui.combination_view` draws the same pair.  Nought when
    neither has anything to draw."""
    frame = _cell(source[0], side)
    source_video = _cell(source[1], side, gray=True)
    if frame is None and source_video is None:
        return 0
    cursor = x
    if frame is not None:
        image.alpha_composite(frame, (cursor, y))
        cursor += side
    if source_video is not None:
        if frame is not None:
            draw.text((cursor + _PLUS_W / 2, y + side / 2), "+", font=_tiny(),
                      anchor="mm", fill=(*TEXT_MUTED, 255))
            cursor += _PLUS_W
        if prompt_edited:
            draw.text((cursor + _PAREN_W / 2, y + side / 2), "(", font=_tiny(),
                      anchor="mm", fill=(*TEXT_MUTED, 255))
            cursor += _PAREN_W
        image.alpha_composite(source_video, (cursor, y))
        cursor += side
        if prompt_edited:
            draw.text((cursor + _PAREN_W / 2, y + side / 2), ")", font=_tiny(),
                      anchor="mm", fill=(*TEXT_MUTED, 255))
            cursor += _PAREN_W
    return cursor - x


def _paint_thumbnails(image, draw, x, y, line: JobLine) -> None:
    """A row's thumbnail, as the strip draws the same one
    (:mod:`origenerator.gui.queue_thumbs`): what the job is made from, else what
    its folder holds."""
    if _paint_source(image, draw, x, y, _CELL, line.source, line.prompt_edited):
        return
    if not line.folder:
        return
    for index in range(FOLDER_CELLS):
        cell_x = x + index * (_CELL + _CELL_GAP)
        drawn = _cell(line.folder[index], _CELL) if index < len(line.folder) else None
        if drawn is None:
            _slot(draw, cell_x, y, _CELL)
        else:
            image.alpha_composite(drawn, (cell_x, y))


def _line(item) -> JobLine:
    frame = resolve_input_image_path(item.source_image)
    return JobLine(
        key=item.key,
        lead=queue_lead_text(item),
        note=starting_row_text(item.starting) or "",
        tooltip=f"{item.caption}\n\n{queue_lead_tooltip(item)}",
        cancelable=item.cancel is not None,
        cancel_tooltip=cancel_tooltip(item.auto_generating),
        shieldable=item.shield is not None,
        shielded=item.shielded,
        can_move_up=item.move_up is not None,
        can_move_down=item.move_down is not None,
        source=(str(frame) if frame is not None else None, item.source_video_thumbnail),
        prompt_edited=item.prompt_edited,
        folder=tuple(str(path) for path in item.folder_thumbnails[:FOLDER_CELLS]),
    )


def _leader(item) -> Leader:
    frame = resolve_input_image_path(item.source_image)
    return Leader(
        key=item.key,
        frame=item.reading.frame,
        source=(str(frame) if frame is not None else None, item.source_video_thumbnail),
        prompt_edited=item.prompt_edited,
        caption=item.reading.caption(),
        compact=item.reading.caption(compact=True),
        progress=item.reading.bars()[0],
        pass_progress=item.reading.bars()[1],
        wait=queue_wait_text(item.foreign_ahead, item.starts_at) or "",
        start_now=seconds_until_start(item.starts_at) is not None,
    )


def queue_section(items, foreign: int = 0, *, first: int = 0,
                  drop_at: int | None = None,
                  pointer: QueuePointer | None = None) -> QueueSection | None:
    """The block the panel hangs at its foot, or ``None`` with nothing to say.
    The head is whatever ComfyUI is making; with nothing of ours in flight it
    names another app's backlog instead."""
    if not items and not foreign:
        return None
    lines = tuple(_line(item) for item in items)
    return QueueSection(lines=lines,
                        leader=_leader(items[0]) if items else None,
                        foreign=foreign,
                        first=max(0, min(first, max(0, len(lines) - ROWS))),
                        drop_at=drop_at, pointer=pointer)


class QueuePointer:
    """The pointer on the block, in the block's own pixels.

    The panel hands it a press, a drag, the button coming up and the wheel,
    and it places each against the rows and buttons as they were last painted:
    a press on a row's arrows, shield or Cancel moves, shields or drops its
    job, one on the row goes to the folder its job will land in once the button
    comes up where it went down, and a press that travels picks the row up and
    drops it further down the line.  Which row the window opens on and where a drag would land are
    the block's own state rather than the line's, kept here because the block
    is painted afresh each beat.
    """

    def __init__(self, host) -> None:
        self._host = host
        self._buttons: list[tuple[tuple, str]] = []
        self.first = 0
        self._press: tuple[str, int, int, bool] | None = None
        self._drag: str | None = None
        self.drop: int | None = None

    def painted(self, targets, origin: tuple[int, int]) -> None:
        left, top = origin
        self._buttons = [((x - left, y - top, width, height), button.command)
                         for (x, y, width, height), button in targets]

    def where(self, command: str) -> tuple | None:
        """Where that button was painted, in the block's own pixels."""
        return next((rect for rect, posted in self._buttons if posted == command), None)

    def press(self, px: int, py: int) -> None:
        verb, _, key = self._command_at(px, py).partition("|")
        if verb in (OPEN, FRAME):
            # A row is pressed for two things -- its folder and a place further
            # down the line -- so the press is held until the release says
            # which.  The head's thumbnail is pressed for the folder alone.
            self._press = (key, px, py, verb == OPEN)
        elif verb in (UP, DOWN):
            item = self._item(key)
            move = None if item is None else item.move_up if verb == UP else item.move_down
            if move is not None:
                move()
        elif verb == SHIELD:
            item = self._item(key)
            if item is not None and item.shield is not None:
                item.shielded = not item.shielded
                item.shield(item.shielded)
        elif verb == CANCEL:
            item = self._item(key)
            if item is not None and item.cancel is not None:
                item.cancel()
        elif verb == CLEAR:
            self._host.clear_foreign_queue()
        elif verb == START_NOW:
            self._host.start_now()

    def drag(self, px: int, py: int) -> None:
        """A press on a row that travels is a drag, and the block marks where it
        would land.  A row that holds its place stays where it is, and nothing
        can be moved in front of it."""
        if self._press is None:
            return
        key, start_x, start_y, draggable = self._press
        if self._drag is None:
            if not draggable or abs(px - start_x) + abs(py - start_y) < _DRAG_START:
                return
            item = self._item(key)
            if item is None or not movable(item):
                self._press = None
                return
            self._drag = key
        self.drop = self._drop_index(py)

    def release(self, px: int, py: int) -> None:
        """The button coming up finishes whatever the press turned out to be."""
        pending, self._press = self._press, None
        dragged, drop = self._drag, self.drop
        self._drag, self.drop = None, None
        if dragged is not None:
            if drop is not None:
                self._drag_to(dragged, drop)
        elif pending is not None:
            item = self._item(pending[0])
            if item is not None:
                item.reveal()

    def wheel(self, steps: int, px: int, py: int) -> None:
        """Scroll the line past the rows the block draws -- over the rows
        themselves, never over the head."""
        if not any(_on(rect, (px, py)) for rect, _key in self._rows()):
            return
        lines = len(self._host.hud_queue[0])
        self.first = max(0, min(self.first - steps, max(0, lines - ROWS)))

    def _command_at(self, px: int, py: int) -> str:
        return next((posted for rect, posted in self._buttons if _on(rect, (px, py))), "")

    def _rows(self) -> list[tuple[tuple, str]]:
        """Each drawn row's rect and the job it stands for, in the order drawn."""
        return [(rect, posted.partition("|")[2]) for rect, posted in self._buttons
                if posted.startswith(f"{OPEN}|")]

    def _item(self, key: str):
        """The job that row stands for, or ``None`` once it has left the line."""
        return next((item for item in self._host.hud_queue[0] if item.key == key), None)

    def _drop_index(self, py: int) -> int:
        """Which slot in the line a drop at ``py`` lands in: above the row whose
        upper half it fell on, else at the end of what is drawn, and never in
        front of a row that holds its place."""
        rows = self._rows()
        slot = next((index for index, (rect, _key) in enumerate(rows)
                     if py < rect[1] + rect[3] / 2), len(rows))
        return max(first_movable(self._host.hud_queue[0]), self.first + slot)

    def _drag_to(self, key: str, target: int) -> None:
        """Ask for *key*'s row to go where it was let go, at *target*.

        Nothing may be moved in front of a row that holds its place, and a row
        let go where it already was asks for nothing.
        """
        items = self._host.hud_queue[0]
        keys = [item.key for item in items]
        if key not in keys:
            return
        # The slot was read with the dragged row still in place, so a drop below
        # it names one further along than it will end up in.
        rest = [other for other in keys if other != key]
        landing = target - 1 if target > keys.index(key) else target
        if rest[:landing] + [key] + rest[landing:] != keys:
            self._host.move(key, rest[landing] if landing < len(rest) else None)

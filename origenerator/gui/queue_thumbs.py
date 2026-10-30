"""The thumbnail on a queue row: what the job is made from, or what its folder holds.

A queued job's own output is the one thing that doesn't exist yet, so a row can
only be recognized by a thumbnail of something *else*. Two somethings, and which
one a row gets is decided by what the job is:

* **What it is made from** — an I2V's start frame, an enhancement's
  original. Two queued videos off the same settings are the same job in every
  respect but the frame they animate, so this is the whole of what tells them
  apart. A combine given a dropped video adds a second cell beside it: that
  video, in gray (:mod:`origenerator.gui.grayscale`). Gray because it is not
  what is being made — drawn in full color, and worse drawn alone, the row reads
  as a job that *is* that clip.
* **What its folder already holds** — for everything else, up to four of the
  folder's own thumbnails. It says nothing about this run in particular; it says
  which collection of the gallery the run is headed for, which is what a thumbnail-less
  job can be placed by at a glance.

Both are drawn into a block of the same width — four square cells in a row, the
height of the row itself — so the text beside them starts at the same place on
every line whether the block holds one thumbnail or four. Laid out across rather
than as a 2×2: stacked, the cells are half the row's height each, which is small
enough that four of them read as one smudge.

Fitted whole into its square cell rather than cover-cropped to fill it: a crop
takes the edges off, and a thumbnail whose subject is not dead center comes out as
a thumbnail of something else. Fitted, every cell shows the whole frame and the
proportions it was made in, with the rest of the square left clear. A folder view
draws its unfilled cells as faint slots, so a folder holding one item reads as a
folder with room in it rather than as a thumbnail that failed to load; a start
frame leaves the rest of the block empty, having nothing to say about how many
thumbnails there might have been.

Every scaled cell is cached by (file, size, gray) — the Job Queue re-renders on
every poll, and a start frame is a full-size render off disk. That fitting and
that cache are :func:`fitted_cell`, public because the pair drawn by
:func:`~origenerator.gui.combination_view.combination_pixmap` is the same kind of
cell, and :func:`fitted_thumbnail`, the same thumbnail without the square around it,
which a dropdown's rows draw; a second cache would be a second full-size decode a
second.
"""
from __future__ import annotations

import os
from collections import OrderedDict

from PyQt6.QtCore import QSize, Qt
from PyQt6.QtGui import QColor, QPainter, QPixmap
from PyQt6.QtWidgets import QLabel
from shared_ui.colors import BORDER_SUBTLE
from shared_ui.spacing import HAIRLINE

from origenerator.gui.combination import Combination, draw_plus, draw_source_video, plus_width
from origenerator.gui.grayscale import grayscale_pixmap
from origenerator.gui.thumbnail_box import centered_in_square, fitted_in

# The gap between cells, in pixels. One is enough to read as separate thumbnails;
# two at this size is a visible stripe between them.
_GAP = HAIRLINE
# How many cells the block has, and so how many of a folder's thumbnails are
# worth carrying. Four is what fits across without the line's text starting
# halfway along the Job Queue.
FOLDER_CELLS = 4


def block_width(cell: int) -> int:
    """How wide a block of :data:`FOLDER_CELLS` cells of ``cell`` pixels is."""
    return FOLDER_CELLS * cell + (FOLDER_CELLS - 1) * _GAP


_CELLS: OrderedDict[tuple[str, int, bool, int | None], QPixmap | None] = OrderedDict()
_MOST_CELLS = 1024


def _written(path) -> int | None:
    """When ``path`` was last written, or None for a file that is not there."""
    try:
        return os.stat(path).st_mtime_ns
    except OSError:
        return None


def fitted_cell(path, side: int, gray: bool = False) -> QPixmap | None:
    """``path`` cropped to a ``side``x``side`` square, or ``None`` if unreadable.

    A missing or unreadable file is an ordinary case here, not an error: a start
    frame can be a library file that has since moved, and a thumbnail can be
    mid-write. The caller draws an empty slot for it.

    ``gray`` drains the color out for a thumbnail shown only for what it configures;
    it is part of the cache key, so one file can be held both ways at once.
    """
    return _held(path, side, gray, squared=True)


def fitted_thumbnail(path, side: int, gray: bool = False) -> QPixmap | None:
    return _held(path, side, gray, squared=False)


def _held(path, side: int, gray: bool, *, squared: bool) -> QPixmap | None:
    if not path:
        return None
    key = (str(path), side, gray, squared, _written(path))
    if key in _CELLS:
        _CELLS.move_to_end(key)
    else:
        fitted = _fitted(QPixmap(str(path)), side, squared)
        _CELLS[key] = (grayscale_pixmap(fitted)
                       if gray and fitted is not None else fitted)
        if len(_CELLS) > _MOST_CELLS:
            _CELLS.popitem(last=False)
    return _CELLS[key]


def _fitted(pixmap: QPixmap, side: int, squared: bool) -> QPixmap | None:
    """``pixmap`` scaled to fit whole inside a ``side``x``side`` square, and when
    ``squared`` centered on it with the rest left clear — letterboxed, or
    pillarboxed for a tall one.

    A squared cell is always the full ``side``, whatever shape went in, so the
    cells stay a grid however mixed the thumbnails in it are.
    """
    if pixmap.isNull():
        return None
    scaled = fitted_in(pixmap, QSize(side, side))
    return centered_in_square(scaled, side) if squared else scaled


def _slot_color() -> QColor:
    """The faint fill of a cell with nothing in it — a slot, not a thumbnail."""
    color = QColor(BORDER_SUBTLE)
    color.setAlpha(110)
    return color


def _canvas(cell: int) -> QPixmap:
    """An empty block, the full width whatever ends up drawn into it."""
    canvas = QPixmap(block_width(cell), cell)
    canvas.fill(Qt.GlobalColor.transparent)
    return canvas


def source_pixmap(made_from: Combination, cell: int) -> QPixmap | None:
    """A block holding what a job is being made from: its thumbnail, and — for a
    combine's run — the source video whose settings it follows, in gray.

    ``None`` only when neither file loads, so the caller can fall back rather than
    show an empty block; either alone still draws, each in its own cell, so the
    two read as one column down the line however few a row has. The cells past
    them stay empty rather than becoming slots: this is not a folder and there is
    no third thumbnail missing from it.

    The source video is drained of color because it is not what is being made. Beside
    the frame in full color it reads as a second subject, and the row of a job
    whose frame hasn't rendered yet would read as a job that *is* that clip.
    """
    frame = fitted_cell(made_from.image, cell)
    source_video = fitted_cell(made_from.source_video, cell, gray=True)
    if frame is None and source_video is None:
        return None
    canvas = _canvas(cell)
    painter = QPainter(canvas)
    if frame is not None:
        painter.drawPixmap(0, 0, frame)
    if source_video is not None:
        if frame is not None:
            draw_plus(painter, cell, cell)
        draw_source_video(painter, cell + plus_width(cell), source_video, made_from.prompt_edited)
    painter.end()
    return canvas


def folder_pixmap(paths, cell: int) -> QPixmap:
    """A block of up to :data:`FOLDER_CELLS` of a folder's thumbnails, across.

    Every cell is drawn, however few files there are — the empty ones are what
    make a short row of thumbnails read as a folder rather than as thumbnails that
    failed to arrive.
    """
    canvas = _canvas(cell)
    painter = QPainter(canvas)
    for index in range(FOLDER_CELLS):
        x = index * (cell + _GAP)
        image = fitted_cell(paths[index], cell) if index < len(paths) else None
        if image is None:
            painter.fillRect(x, 0, cell, cell, _slot_color())
        else:
            painter.drawPixmap(x, 0, image)
    painter.end()
    return canvas


class QueueThumbs(QLabel):
    """One row's thumbnail block, at a fixed size it never asks to grow past.

    :meth:`show_source` and :meth:`show_folder` each re-render only when what
    they were handed has changed: the Job Queue pushes every row a fresh view-model
    on every poll, and recomposing four scaled cells a second and a half apart
    for a queue that hasn't moved is work nobody sees.
    """

    def __init__(self, cell: int, parent=None):
        super().__init__(parent)
        self._cell = cell
        self._showing = None  # what is drawn, so an unchanged push costs nothing
        self.setFixedSize(block_width(cell), cell)
        # Left, so a block holding one thumbnail starts where a block holding four
        # does and the two read as one column down the line.
        self.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        # The row it sits in handles the click that opens the folder and the drag
        # that reorders the line; a child widget under the cursor would eat both.
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.hide()  # nothing to show yet, and an empty block would claim there was

    def show_source(self, made_from: Combination) -> bool:
        """Draw what a job is made from: its start frame, and beside it the
        source video's thumbnail, in gray.

        ``False`` only when neither has anything to draw: no thumbnail and no
        source video, or files that have moved or haven't been rendered yet (a video
        queued after the image it animates is exactly that). The caller falls
        back to the folder view rather than leave a blank block standing where a
        thumbnail was promised — but a frame that hasn't landed no longer costs the
        row its source video's cell, which is about this run either way.
        """
        showing = ("source", made_from)
        if self._showing == showing:
            return True
        pixmap = source_pixmap(made_from, self._cell)
        if pixmap is None:
            return False
        self._showing = showing
        self.setPixmap(pixmap)
        self.show()
        return True

    def show_folder(self, paths):
        """Draw up to four of a folder's thumbnails across the block."""
        paths = [str(p) for p in list(paths)[:FOLDER_CELLS]]
        if self._showing == ("folder", tuple(paths)):
            return
        self._showing = ("folder", tuple(paths))
        self.setPixmap(folder_pixmap(paths, self._cell))
        self.show()

    def clear_block(self):
        """Take the block off the row entirely — nothing to show and no empty
        square left claiming there was."""
        if self._showing is None:
            return
        self._showing = None
        self.clear()
        self.hide()

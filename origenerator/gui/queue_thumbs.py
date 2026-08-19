"""The picture on a queue row: what the job is made from, or what its folder holds.

A queued job's own output is the one thing that doesn't exist yet, so a row can
only be recognized by a picture of something *else*. Two somethings, and which
one a row gets is decided by what the job is:

* **What it is made from** — an image-to-video's start frame, an enhancement's
  original. Two queued videos off the same recipe are the same job in every
  respect but the frame they animate, so this is the whole of what tells them
  apart. A combine given a dropped video adds a second cell beside it: that
  video, in gray (:mod:`origenerator.gui.grayscale`). Gray because it is not
  what is being made — drawn in full color, and worse drawn alone, the row reads
  as a job that *is* that clip.
* **What its folder already holds** — for everything else, up to four of the
  folder's own thumbnails. It says nothing about this run in particular; it says
  which shelf of the gallery the run is headed for, which is what a picture-less
  job can be placed by at a glance.

Both are drawn into a block of the same width — four square cells in a row, the
height of the row itself — so the text behind them starts at the same place on
every line whether the block holds one picture or four. Laid out across rather
than as a 2×2: stacked, the cells are half the row's height each, which is small
enough that four of them read as one smudge.

Fitted whole into its square cell rather than cover-cropped to fill it: a crop
takes the edges off, and a picture whose subject is not dead center comes out as
a picture of something else. Fitted, every cell shows the whole frame and the
proportions it was made in, with the rest of the square left clear. A folder view
draws its unfilled cells as faint slots, so a folder holding one item reads as a
folder with room in it rather than as a picture that failed to load; a start
frame leaves the rest of the block empty, having nothing to say about how many
pictures there might have been.

Every scaled cell is cached by (file, size, gray) for the life of the session —
the strip re-renders on every poll, and a start frame is a full-size render off
disk.
"""

from PyQt6.QtWidgets import QLabel
from PyQt6.QtGui import QPixmap, QPainter, QColor
from PyQt6.QtCore import Qt

from origenerator.gui.grayscale import grayscale_pixmap
from origenerator.paths import ensure_shared_ui_on_path
from origenerator.workflows.derived_size import resolve_input_image_path

ensure_shared_ui_on_path()
from shared_ui.colors import BORDER_SUBTLE

# The gap between cells, in pixels. One is enough to read as separate pictures;
# two at this size is a visible stripe between them.
_GAP = 1
# How many cells the block has, and so how many of a folder's thumbnails are
# worth carrying. Four is what fits across without the line's text starting
# halfway along the strip.
FOLDER_CELLS = 4


def block_width(cell: int) -> int:
    """How wide a block of :data:`FOLDER_CELLS` cells of ``cell`` pixels is."""
    return FOLDER_CELLS * cell + (FOLDER_CELLS - 1) * _GAP


# (file, side, gray) -> the cell-sized pixmap, or None for a file that wouldn't
# load. Unbounded on purpose: an entry is a few kilobytes, and the set of files in
# flight over one session is small — where the cost being avoided is decoding a
# multi-megabyte render on the UI thread every poll.
_CELLS: dict[tuple[str, int, bool], QPixmap | None] = {}


def _cell(path, side: int, gray: bool = False) -> QPixmap | None:
    """``path`` cropped to a ``side``x``side`` square, or ``None`` if unreadable.

    A missing or unreadable file is an ordinary case here, not an error: a start
    frame can be a library file that has since moved, and a thumbnail can be
    mid-write. The caller draws an empty slot for it.

    ``gray`` drains the color out for a picture shown only for what it configures;
    it is part of the cache key, so one file can be held both ways at once.
    """
    if not path:
        return None
    key = (str(path), side, gray)
    if key not in _CELLS:
        fitted = _fit_in_square(QPixmap(str(path)), side)
        _CELLS[key] = (grayscale_pixmap(fitted)
                       if gray and fitted is not None else fitted)
    return _CELLS[key]


def _fit_in_square(pixmap: QPixmap, side: int) -> QPixmap | None:
    """``pixmap`` scaled to fit whole inside a ``side``x``side`` square, centered,
    the rest of the square left clear — letterboxed, or pillarboxed for a tall one.

    The square itself is always the full ``side``, whatever shape went in, so the
    cells stay a grid however mixed the pictures in it are.
    """
    if pixmap.isNull():
        return None
    scaled = pixmap.scaled(
        side, side,
        Qt.AspectRatioMode.KeepAspectRatio,
        Qt.TransformationMode.SmoothTransformation,
    )
    cell = QPixmap(side, side)
    cell.fill(Qt.GlobalColor.transparent)
    painter = QPainter(cell)
    painter.drawPixmap((side - scaled.width()) // 2, (side - scaled.height()) // 2,
                       scaled)
    painter.end()
    return cell


def _slot_color() -> QColor:
    """The faint fill of a cell with nothing in it — a slot, not a picture."""
    color = QColor(BORDER_SUBTLE)
    color.setAlpha(110)
    return color


def _canvas(cell: int) -> QPixmap:
    """An empty block, the full width whatever ends up drawn into it."""
    canvas = QPixmap(block_width(cell), cell)
    canvas.fill(Qt.GlobalColor.transparent)
    return canvas


def source_pixmap(path, cell: int, recipe=None) -> QPixmap | None:
    """A block holding what a job is being made from: the file at ``path``, and —
    for a combine's run — the ``recipe`` video whose settings it follows, in gray.

    ``None`` only when neither file loads, so the caller can fall back rather than
    show an empty block; either alone still draws, each in its own cell, so the
    two read as one column down the line however few a row has. The cells past
    them stay empty rather than becoming slots: this is not a folder and there is
    no third picture missing from it.

    The recipe is drained of color because it is not what is being made. Beside
    the frame in full color it reads as a second subject, and the row of a job
    whose frame hasn't rendered yet would read as a job that *is* that clip.
    """
    parts = (_cell(path, cell), _cell(recipe, cell, gray=True))
    if all(part is None for part in parts):
        return None
    canvas = _canvas(cell)
    painter = QPainter(canvas)
    for index, part in enumerate(parts):
        if part is not None:
            painter.drawPixmap(index * (cell + _GAP), 0, part)
    painter.end()
    return canvas


def folder_pixmap(paths, cell: int) -> QPixmap:
    """A block of up to :data:`FOLDER_CELLS` of a folder's thumbnails, across.

    Every cell is drawn, however few files there are — the empty ones are what
    make a short row of pictures read as a folder rather than as pictures that
    failed to arrive.
    """
    canvas = _canvas(cell)
    painter = QPainter(canvas)
    for index in range(FOLDER_CELLS):
        x = index * (cell + _GAP)
        picture = _cell(paths[index], cell) if index < len(paths) else None
        if picture is None:
            painter.fillRect(x, 0, cell, cell, _slot_color())
        else:
            painter.drawPixmap(x, 0, picture)
    painter.end()
    return canvas


class QueueThumbs(QLabel):
    """One row's picture block, at a fixed size it never asks to grow past.

    :meth:`show_source` and :meth:`show_folder` each re-render only when what
    they were handed has changed: the strip pushes every row a fresh view-model
    on every poll, and recomposing four scaled cells a second and a half apart
    for a queue that hasn't moved is work nobody sees.
    """

    def __init__(self, cell: int, parent=None):
        super().__init__(parent)
        self._cell = cell
        self._showing = None  # what is drawn, so an unchanged push costs nothing
        self.setFixedSize(block_width(cell), cell)
        # Left, so a block holding one picture starts where a block holding four
        # does and the two read as one column down the line.
        self.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        # The row it sits in handles the click that opens the folder and the drag
        # that reorders the line; a child widget under the cursor would eat both.
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.hide()  # nothing to show yet, and an empty block would claim there was

    def show_source(self, image_ref, recipe=None) -> bool:
        """Draw what ``image_ref`` names — a job's start frame, as its
        ``LoadImage`` reference rather than a path, which is the form every run
        records it in — and beside it the ``recipe`` video's thumbnail, in gray.

        ``False`` only when neither has anything to draw: no reference and no
        recipe, or files that have moved or haven't been rendered yet (a video
        queued behind the image it animates is exactly that). The caller falls
        back to the folder view rather than leave a blank block standing where a
        picture was promised — but a frame that hasn't landed no longer costs the
        row its recipe cell, which is about this run either way.

        The frame is resolved on every call rather than remembered: the answer
        changes the moment it lands, and it is one stat.
        """
        path = resolve_input_image_path(image_ref) if image_ref else None
        showing = ("source", str(path) if path else None,
                   str(recipe) if recipe else None)
        if self._showing == showing:
            return True
        pixmap = source_pixmap(path, self._cell, recipe)
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
        square left behind claiming there was."""
        if self._showing is None:
            return
        self._showing = None
        self.clear()
        self.hide()

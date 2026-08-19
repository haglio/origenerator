"""The picture on a queue row: what the job is made from, or what its folder holds.

A queued job's own output is the one thing that doesn't exist yet, so a row can
only be recognized by a picture of something *else*. Two somethings, and which
one a row gets is decided by what the job is:

* **What it is made from** — an image-to-video's start frame, an enhancement's
  original. One cell, the picture itself. Two queued videos off the same recipe
  are the same job in every respect but the frame they animate, so this is the
  whole of what tells them apart.
* **What its folder already holds** — for everything else, up to four of the
  folder's own thumbnails. It says nothing about this run in particular; it says
  which shelf of the gallery the run is headed for, which is what a picture-less
  job can be placed by at a glance.

Both are drawn into a block of the same width — four square cells in a row, the
height of the row itself — so the text behind them starts at the same place on
every line whether the block holds one picture or four. Laid out across rather
than as a 2×2: stacked, the cells are half the row's height each, which is small
enough that four of them read as one smudge.

Cover-cropped to square cells rather than fitted into them: at this size a
letterboxed thumbnail is mostly letterbox, and the middle of a frame is where the
subject is. A folder view draws its unfilled cells as faint slots, so a folder
holding one item reads as a folder with room in it rather than as a picture that
failed to load; a start frame leaves the rest of the block empty, having nothing
to say about how many pictures there might have been.

Every scaled cell is cached by (file, size) for the life of the session — the
strip re-renders on every poll, and a start frame is a full-size render off disk.
"""

from PyQt6.QtWidgets import QLabel
from PyQt6.QtGui import QPixmap, QPainter, QColor
from PyQt6.QtCore import Qt

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


# (file, side) -> the cell-sized pixmap, or None for a file that wouldn't load.
# Unbounded on purpose: an entry is a few kilobytes, and the set of files in
# flight over one session is small — where the cost being avoided is decoding a
# multi-megabyte render on the UI thread every poll.
_CELLS: dict[tuple[str, int], QPixmap | None] = {}


def _cell(path, side: int) -> QPixmap | None:
    """``path`` cropped to a ``side``x``side`` square, or ``None`` if unreadable.

    A missing or unreadable file is an ordinary case here, not an error: a start
    frame can be a library file that has since moved, and a thumbnail can be
    mid-write. The caller draws an empty slot for it.
    """
    if not path:
        return None
    key = (str(path), side)
    if key not in _CELLS:
        _CELLS[key] = _crop_to_square(QPixmap(str(path)), side)
    return _CELLS[key]


def _crop_to_square(pixmap: QPixmap, side: int) -> QPixmap | None:
    """Fill a ``side``x``side`` square with the middle of ``pixmap``."""
    if pixmap.isNull():
        return None
    scaled = pixmap.scaled(
        side, side,
        Qt.AspectRatioMode.KeepAspectRatioByExpanding,
        Qt.TransformationMode.SmoothTransformation,
    )
    return scaled.copy((scaled.width() - side) // 2, (scaled.height() - side) // 2,
                       side, side)


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


def source_pixmap(path, cell: int) -> QPixmap | None:
    """A block holding one picture — the file a job is being made from.

    ``None`` when the file won't load, so the caller can fall back rather than
    show an empty block. The cells beside it stay empty rather than becoming
    slots: this is not a folder and there is no second picture missing from it.
    """
    picture = _cell(path, cell)
    if picture is None:
        return None
    canvas = _canvas(cell)
    painter = QPainter(canvas)
    painter.drawPixmap(0, 0, picture)
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

    def show_source(self, image_ref) -> bool:
        """Draw what ``image_ref`` names — a job's start frame, as its
        ``LoadImage`` reference rather than a path, which is the form every run
        records it in.

        ``False`` when there is nothing to draw: no reference, or a file that has
        moved or hasn't been rendered yet (a video queued behind the image it
        animates is exactly that). The caller falls back to the folder view rather
        than leave a blank block standing where a picture was promised.

        Resolved on every call rather than remembered: the answer changes the
        moment the frame lands, and it is one stat.
        """
        path = resolve_input_image_path(image_ref) if image_ref else None
        if path is None:
            return False
        if self._showing == ("source", str(path)):
            return True
        pixmap = source_pixmap(path, self._cell)
        if pixmap is None:
            return False
        self._showing = ("source", str(path))
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

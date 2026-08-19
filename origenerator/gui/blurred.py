"""A picture stood behind something that hasn't been drawn yet.

A queued generation has no picture of its own — that is the whole of what is
being waited for — so its card is a blank plate with a word on it, and a line of
them is a line of identical blank plates. But a run usually came from somewhere:
an image-to-video's start frame, an enhancement's original, and every image a
request was made of. That picture is not what is being made, so it cannot be
shown as it is; blurred and dimmed it says the right thing instead — something is
coming, and it will be about this.

Blurred by scaling the picture right down and back up again, which is a box blur
the graphics stack does for free, rather than by a real convolution: at this size
the difference is invisible and the cost is a hundredth of it. Cover-cropped
first, so the plate fills edge to edge with no letterboxing.

Cached by file and size for the life of the session — the shelves and the folder
grid rebuild on every poll, and this reads a full-size render off disk.
"""

from pathlib import Path

from PyQt6.QtCore import QSize, Qt
from PyQt6.QtGui import QColor, QPainter, QPixmap

# How far down the picture goes before coming back up. Sixteen turns a card-sized
# frame into about ten pixels across, which is soft enough that nothing in it
# can be made out and coarse enough to still carry the picture's colors.
_BLUR_DIVISOR = 16
# How much black is laid over it. Enough that it reads as a backdrop rather than
# as the result, and that the stage word over it stays legible.
_DIM = 0.55

_CACHE: dict[tuple, QPixmap | None] = {}


def blurred_backdrop(path, size: QSize) -> QPixmap | None:
    """``path`` as a soft, dimmed plate of ``size``, or ``None`` when there is no
    picture there to use — a file the library has since moved is an ordinary case
    here, not an error."""
    if not path:
        return None
    key = (str(path), size.width(), size.height())
    if key not in _CACHE:
        _CACHE[key] = _render(path, size)
    return _CACHE[key]


def _render(path, size: QSize) -> QPixmap | None:
    if not Path(path).is_file() or size.width() <= 0 or size.height() <= 0:
        return None
    picture = QPixmap(str(path))
    if picture.isNull():
        return None
    covering = picture.scaled(size, Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                              Qt.TransformationMode.SmoothTransformation)
    plate = covering.copy((covering.width() - size.width()) // 2,
                          (covering.height() - size.height()) // 2,
                          size.width(), size.height())
    small = plate.scaled(max(1, size.width() // _BLUR_DIVISOR),
                         max(1, size.height() // _BLUR_DIVISOR),
                         Qt.AspectRatioMode.IgnoreAspectRatio,
                         Qt.TransformationMode.SmoothTransformation)
    blurred = small.scaled(size, Qt.AspectRatioMode.IgnoreAspectRatio,
                           Qt.TransformationMode.SmoothTransformation)
    painter = QPainter(blurred)
    painter.fillRect(blurred.rect(), QColor(0, 0, 0, int(255 * _DIM)))
    painter.end()
    return blurred

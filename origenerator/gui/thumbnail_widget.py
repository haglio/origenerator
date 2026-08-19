from pathlib import Path

from PyQt6.QtWidgets import QWidget, QVBoxLayout, QLabel, QPushButton, QApplication
from PyQt6.QtGui import QPixmap, QDrag, QCursor
from PyQt6.QtCore import Qt, QPoint, QSize, QEvent, pyqtSignal

from origenerator.gui.drag_thumbnail import label_thumbnail, set_drag_thumbnail
from origenerator.gui.enhanced_badge import EnhancedBadge
from origenerator.gui.generation_drag import generation_mime
from origenerator.gui.looping_preview import looping_movie
from origenerator.gui.media_badge import MediaBadge
from origenerator.gui.star_badge import StarBadge

_IMAGE_SIZE = QSize(172, 160)  # the thumbnail image area, inside the 180x200 tile

# Hover-revealed corner action buttons (an i2v tile's per-seed re-rolls): a small
# translucent chip in the top-left, blue on hover, sized to sit over the thumbnail.
_CORNER_INSET = 6
_CORNER_SIZE = 28
_CORNER_GAP = 4
_CORNER_BUTTON_CSS = (
    "QPushButton { background: rgba(0,0,0,0.55); border: none; border-radius: 6px; }"
    "QPushButton:hover { background: rgba(48,128,224,0.9); }"
)

# A selected thumbnail lightens its whole tile — behind both the image and the
# caption — the way a file browser highlights a picked item. Two things make
# the fill actually show:
#   * WA_StyledBackground, or a plain QWidget subclass paints no stylesheet
#     background at all; and
#   * transparent child labels, or the app's global `QWidget { background-color }`
#     paints them opaque and the fill only peeks through the 4px margin as a
#     frame (which is what an earlier attempt did).
# The image also lightens its resting border a touch when selected.
_SELECTED_BG = "#3a3a3a"
_SELECTED_TILE_CSS = f"#thumbnailTile {{ background-color: {_SELECTED_BG}; border-radius: 4px; }}"
_BORDER_UNSELECTED = "2px solid #3f3f3f"
_BORDER_SELECTED = "2px solid #8a8a8a"


class ThumbnailWidget(QWidget):
    clicked = pyqtSignal(str)  # prompt_id
    double_clicked = pyqtSignal(str)  # prompt_id — an "open" gesture
    context_requested = pyqtSignal(str, QPoint)  # prompt_id, global position
    drag_started = pyqtSignal(str)  # prompt_id — a drag of this tile began
    drag_ended = pyqtSignal()       # that drag finished (dropped or canceled)
    corner_action_triggered = pyqtSignal(str, str)  # prompt_id, action_id

    def __init__(self, prompt_id: str, thumb_path: str | None, label_text: str,
                 parent=None, *, media_type: str | None = None,
                 movie_path: str | None = None, starred: bool = False,
                 enhanced: bool = False, enhancing: bool = False,
                 corner_actions: list | None = None):
        super().__init__(parent)
        self.prompt_id = prompt_id
        self._selected = False
        self._starred = starred
        self._enhancing = enhancing
        # The tile's own picture, held aside while a running enhancement streams
        # its frames over the top, so the end of the run restores it.
        self._resting_pixmap: QPixmap | None = None
        self._corner_buttons: list[QPushButton] = []
        self._press_pos: QPoint | None = None  # left-press origin, for drag detection
        self.setObjectName("thumbnailTile")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        # Right-click anywhere on the tile asks the gallery for a context menu.
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(
            lambda pos: self.context_requested.emit(self.prompt_id, self.mapToGlobal(pos))
        )
        self.setFixedSize(180, 200)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(2)

        self._image_label = QLabel()
        self._image_label.setFixedSize(_IMAGE_SIZE)
        self._image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        # A video tile loops its short WebP preview; an image (or a video whose
        # WebP couldn't be built) shows its static frame.
        if movie_path and Path(movie_path).exists():
            movie = looping_movie(movie_path, _IMAGE_SIZE, self._image_label)
            self._image_label.setMovie(movie)
            movie.start()
        elif thumb_path and Path(thumb_path).exists():
            pm = QPixmap(str(thumb_path))
            self._image_label.setPixmap(
                pm.scaled(_IMAGE_SIZE, Qt.AspectRatioMode.KeepAspectRatio,
                          Qt.TransformationMode.SmoothTransformation)
            )
        else:
            self._image_label.setText("No preview")

        self._text_label = QLabel(label_text)
        self._text_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._text_label.setWordWrap(True)
        self._text_label.setMaximumHeight(30)
        # Transparent so the tile's fill shows through behind the caption.
        self._text_label.setStyleSheet("background-color: transparent;")

        # Let mouse events (clicks, hover) fall through to the tile, so enter/leave
        # track the whole tile instead of flickering as the cursor crosses a child.
        self._image_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self._text_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)

        layout.addWidget(self._image_label)
        layout.addWidget(self._text_label)
        self._apply_styles()

        # In a mixed listing (the Recents shelf) a corner badge names the kind;
        # inside a single-type folder the caller leaves it off as redundant.
        if media_type:
            MediaBadge(media_type, self)

        # A green star in the opposite (top-right) corner marks a bookmarked item,
        # shown only while starred so an unstarred tile stays clean.
        self._star_badge = StarBadge(self)
        self._star_badge.setVisible(self._starred)

        # A yellow plus in the bottom-right of the image area marks an enhanced
        # image (upscaled + re-sampled), clear of the other corners' badges.
        self._enhanced_badge = None
        if enhanced:
            image_bottom = layout.contentsMargins().top() + _IMAGE_SIZE.height()
            self._enhanced_badge = EnhancedBadge(self, image_bottom)

        # While an enhancement of this image is cooking, a scrim over the picture
        # says so without hiding it: the base render is out and worth looking at
        # — that is the point of generating it first — and only the caption tells
        # you a better version is coming.
        self._enhancing_overlay = QLabel("Enhancing…", self)
        self._enhancing_overlay.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._enhancing_overlay.setStyleSheet(
            "background-color: rgba(0, 0, 0, 0.45); color: white;"
            " font-weight: 600; border-radius: 3px;"
        )
        self._enhancing_overlay.setAttribute(
            Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self._enhancing_overlay.setGeometry(self._image_label.geometry())
        self._enhancing_overlay.setVisible(self._enhancing)

        # An i2v folder's tiles carry top-left hover controls to re-roll one seed
        # on its own; other tiles pass none and grow no buttons.
        self._build_corner_actions(corner_actions or [])

    def is_selected(self) -> bool:
        return self._selected

    def set_selected(self, selected: bool):
        """Lighten the whole tile when selected; restore the resting look when not."""
        if selected == self._selected:
            return  # idempotent: skip restyling thumbnails a click didn't move
        self._selected = selected
        self._apply_styles()

    def is_starred(self) -> bool:
        return self._starred

    def set_starred(self, starred: bool):
        """Show or hide the corner star as the item's bookmark is toggled."""
        if starred == self._starred:
            return
        self._starred = starred
        self._star_badge.setVisible(starred)

    def is_enhancing(self) -> bool:
        return self._enhancing

    def set_enhancing(self, enhancing: bool):
        """Show or clear the "Enhancing…" scrim as a run starts and lands.

        A run that ends puts the tile's own picture back: the streamed frames
        are a partial render of a file that doesn't exist yet, so once the run
        is over they are no longer of anything. (A landed enhancement folds onto
        the row and the rebuild redraws the tile from the new file; a cancelled
        one leaves the base render, which is what was there before.)"""
        if enhancing == self._enhancing:
            return
        self._enhancing = enhancing
        if not enhancing and self._resting_pixmap is not None:
            self._image_label.setPixmap(self._resting_pixmap)
            self._resting_pixmap = None
        self._enhancing_overlay.setGeometry(self._image_label.geometry())
        self._enhancing_overlay.setVisible(enhancing)
        self._enhancing_overlay.raise_()

    def show_enhancing_frame(self, frame: bytes):
        """Paint the latest frame of the enhancement being made of this image.

        The tile is where the user is looking while a folder enhances itself, so
        the run streams here as well as in the info pane — the scrim stays over
        the top, because what is on the tile is still not the finished file."""
        pixmap = QPixmap()
        if not pixmap.loadFromData(frame) or pixmap.isNull():
            return
        if self._resting_pixmap is None:
            self._resting_pixmap = self._image_label.pixmap()
        self._image_label.setPixmap(
            pixmap.scaled(_IMAGE_SIZE, Qt.AspectRatioMode.KeepAspectRatio,
                          Qt.TransformationMode.SmoothTransformation)
        )
        self._enhancing_overlay.setGeometry(self._image_label.geometry())
        self._enhancing_overlay.raise_()

    def _apply_styles(self):
        if self._selected:
            self.setStyleSheet(_SELECTED_TILE_CSS)
            border = _BORDER_SELECTED
        else:
            self.setStyleSheet("")
            border = _BORDER_UNSELECTED
        # Transparent background so the tile fill shows behind any letterboxing.
        self._image_label.setStyleSheet(
            f"background-color: transparent; border: {border}; border-radius: 3px;"
        )

    # --- corner action buttons (hover-revealed per-seed re-rolls) -----------

    def _build_corner_actions(self, actions: list):
        """Lay out one hidden top-left button per ``(action_id, icon, tooltip)``.

        Each fires :attr:`corner_action_triggered` with this tile's prompt_id and
        its action_id. Hidden until the tile is hovered (see :meth:`enterEvent`);
        an event filter keeps them up while the cursor sits on a button rather than
        the tile itself, so they don't flicker out from under the pointer.
        """
        for i, (action_id, icon, tooltip) in enumerate(actions):
            button = QPushButton(self)
            button.setIcon(icon)
            button.setIconSize(QSize(_CORNER_SIZE - 8, _CORNER_SIZE - 8))
            button.setToolTip(tooltip)
            button.setFixedSize(_CORNER_SIZE, _CORNER_SIZE)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setStyleSheet(_CORNER_BUTTON_CSS)
            button.move(_CORNER_INSET + i * (_CORNER_SIZE + _CORNER_GAP), _CORNER_INSET)
            button.setVisible(False)
            button.installEventFilter(self)  # keep the set up while hovering a button
            button.clicked.connect(lambda _=False, a=action_id: self.corner_action_triggered.emit(self.prompt_id, a))
            self._corner_buttons.append(button)

    def _set_corner_actions_visible(self, visible: bool):
        for button in self._corner_buttons:
            button.setVisible(visible)

    def _cursor_over_tile(self) -> bool:
        """Whether the pointer is still anywhere within the tile — including over a
        corner button — so leaving for a button doesn't read as leaving the tile."""
        return self.rect().contains(self.mapFromGlobal(QCursor.pos()))

    def eventFilter(self, obj, event):
        # A button is a child, so the cursor leaving it (back onto the tile, or off
        # the tile entirely) is where an off-tile exit from a button surfaces.
        if event.type() == QEvent.Type.Leave and obj in self._corner_buttons:
            if not self._cursor_over_tile():
                self._set_corner_actions_visible(False)
        return super().eventFilter(obj, event)

    def enterEvent(self, event):
        self._set_corner_actions_visible(True)
        super().enterEvent(event)

    def leaveEvent(self, event):
        if not self._cursor_over_tile():  # moving onto a button isn't leaving the tile
            self._set_corner_actions_visible(False)
        super().leaveEvent(event)

    def mousePressEvent(self, event):
        # Only a left click (re)selects. A right click opens the context menu via
        # the custom-context-menu signal and must NOT collapse a multi-selection.
        if event.button() == Qt.MouseButton.LeftButton:
            self._press_pos = event.position().toPoint()  # origin for a possible drag
            self.clicked.emit(self.prompt_id)

    def mouseMoveEvent(self, event):
        # Drag the generation out to a combine drop slot, but only once the press
        # has travelled far enough to read as a drag rather than a click — so a
        # plain click still just selects, and a double-click still opens.
        if self._press_pos is None or not (event.buttons() & Qt.MouseButton.LeftButton):
            return
        moved = (event.position().toPoint() - self._press_pos).manhattanLength()
        if moved < QApplication.startDragDistance():
            return
        self._press_pos = None
        drag = QDrag(self)
        drag.setMimeData(generation_mime(self.prompt_id))
        # The tile's picture trails the cursor — the frame a video tile's looping
        # WebP is on, as much as a still image's pixmap.
        set_drag_thumbnail(drag, label_thumbnail(self._image_label))
        # Announce the drag so a combine slot can light up the moment it starts —
        # QDrag.exec is modal, so the highlight is on for the whole gesture.
        self.drag_started.emit(self.prompt_id)
        try:
            drag.exec(Qt.DropAction.CopyAction)
        finally:
            self.drag_ended.emit()

    def mouseDoubleClickEvent(self, event):
        # A left double-click is an "open" gesture; the first click's press has
        # already selected the tile, so the handler acts on the current selection.
        if event.button() == Qt.MouseButton.LeftButton:
            self.double_clicked.emit(self.prompt_id)

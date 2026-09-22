from __future__ import annotations

from PyQt6.QtCore import QPoint, QSize, Qt, pyqtSignal
from PyQt6.QtGui import QPixmap
from PyQt6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from origenerator.gui import grid_card, icons, palette

# The collage's four cells fill the card's picture area, a gap apart.
_CELL_GAP = 2
_CELL_SIZE = ((grid_card.PICTURE_SIZE[0] - _CELL_GAP) // 2,
              (grid_card.PICTURE_SIZE[1] - _CELL_GAP) // 2)
_INNER_WIDTH = grid_card.CARD_WIDTH - 2 * grid_card.CARD_MARGIN


class FolderTile(QFrame):
    """A folder shown in the main view: a thumbnail collage plus name + count.

    Clicking drills into the folder; right-clicking asks for a context menu.
    Both signals carry the folder's stable key so the view can act on it.
    ``detail`` is what the name doesn't say (a settings folder's prompt and
    settings), shown on hover.
    """

    clicked = pyqtSignal(str)
    context_requested = pyqtSignal(str, QPoint)

    _BADGE = 16  # on-tile size of the recipe-level chip

    def __init__(self, key, text, preview_paths, count, favorite=False,
                 context="", level=None, detail="", parent=None):
        super().__init__(parent)
        self._key = key
        self.setObjectName("folderTile")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        # The same card the generations beside it in the flow stand in, plus the
        # breadcrumb line the Favorites shelf's tiles carry.
        self.setFixedSize(*grid_card.folder_card_size(breadcrumb=bool(context)))
        self.setStyleSheet(grid_card.idle_css("folderTile"))
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(
            lambda pos: self.context_requested.emit(self._key, self.mapToGlobal(pos))
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(*(grid_card.CARD_MARGIN,) * 4)
        layout.setSpacing(grid_card.CARD_SPACING)
        self._collage = self._build_collage(preview_paths)
        layout.addWidget(self._collage)

        if context:
            # Where this folder lives, so a favorited folder is tellable apart from a
            # same-named one elsewhere. Elided from the left to keep the tail — the
            # folder's own parent — visible; the whole path sits in the tooltip.
            crumb = QLabel()
            crumb.setStyleSheet("color: #7a7a7a; font-size: 10px;")
            crumb.setFixedHeight(grid_card.BREADCRUMB_HEIGHT)
            crumb.setText(crumb.fontMetrics().elidedText(
                context, Qt.TextElideMode.ElideLeft, _INNER_WIDTH))
            crumb.setToolTip(context)
            layout.addWidget(crumb)

        # The name, led by its recipe-level chip when the folder has one (the same
        # badge the tree shows), so a Favorites-shelf tile is placeable even out of
        # its parent's context.
        caption_row = QHBoxLayout()
        caption_row.setContentsMargins(0, 0, 0, 0)
        caption_row.setSpacing(4)
        if level is not None:
            caption_row.addWidget(self._level_badge(level), 0, Qt.AlignmentFlag.AlignTop)
        self._text = text
        self._caption = caption = QLabel(self._captioned(favorite))
        caption.setWordWrap(True)
        grid_card.style_caption(caption)  # the grid's shared caption size
        # A settings folder is named by a code, so what it holds — the prompt and
        # the settings that set it apart — is read on hover rather than under the
        # collage, where it would take more of the tile than the pictures do.
        caption.setToolTip(detail or text)
        caption_row.addWidget(caption, 1)
        layout.addLayout(caption_row)

        count_label = QLabel(f"{count} item{'s' if count != 1 else ''}")
        count_label.setStyleSheet("color: #9a9a9a; font-size: 10px;")
        count_label.setFixedHeight(grid_card.COUNT_HEIGHT)
        layout.addWidget(count_label)

    @property
    def key(self) -> str:
        return self._key

    def set_favorite(self, favorite: bool) -> None:
        self._caption.setText(self._captioned(favorite))

    def _captioned(self, favorite: bool) -> str:
        return ("★ " if favorite else "") + self._text

    def _level_badge(self, level) -> QLabel:
        """The lettered recipe-level chip, tooltip'd with the level's full name."""
        badge = QLabel()
        badge.setFixedSize(self._BADGE, self._BADGE)
        badge.setPixmap(icons.level_badge_icon(level).pixmap(QSize(self._BADGE, self._BADGE)))
        badge.setToolTip(icons.LEVEL_LABELS[level])
        return badge

    @staticmethod
    def _build_collage(preview_paths) -> QWidget:
        collage = QWidget()
        collage.setFixedSize(grid_card.picture_size())
        grid = QGridLayout(collage)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(_CELL_GAP)
        previews = list(preview_paths)[:4]
        if not previews:
            placeholder = QLabel("empty")
            placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
            placeholder.setStyleSheet(
                f"color: #6a6a6a; background: {palette.EMPTY_PLATE}; border-radius: 2px;")
            placeholder.setFixedSize(grid_card.picture_size())
            grid.addWidget(placeholder, 0, 0)
            return collage
        for idx in range(4):
            cell = QLabel()
            cell.setFixedSize(*_CELL_SIZE)
            cell.setAlignment(Qt.AlignmentFlag.AlignCenter)
            cell.setStyleSheet(
                f"background: {palette.EMPTY_PLATE}; border-radius: 2px;")
            if idx < len(previews):
                pm = QPixmap(str(previews[idx]))
                if not pm.isNull():
                    cell.setPixmap(pm.scaled(
                        *_CELL_SIZE,
                        Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                        Qt.TransformationMode.SmoothTransformation,
                    ))
            grid.addWidget(cell, idx // 2, idx % 2)
        return collage

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self._key)

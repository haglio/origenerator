from __future__ import annotations

import html

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
from shared_ui.colors import TEXT_PRIMARY
from shared_ui.icons import marked_text
from shared_ui.palette import TEXT_MUTED, as_hex
from shared_ui.spacing import BUTTON_ICON, BUTTON_RADIUS, GAP_SMALL, HAIRLINE

from origenerator.gui import palette, tile_shape

# The four thumbnails fill the tile's thumbnail area, a gap apart.
_CELL_GAP = HAIRLINE
_CELL_SIZE = ((tile_shape.THUMBNAIL_SIZE[0] - _CELL_GAP) // 2,
              (tile_shape.THUMBNAIL_SIZE[1] - _CELL_GAP) // 2)
_INNER_WIDTH = tile_shape.TILE_WIDTH - 2 * tile_shape.TILE_MARGIN


class FolderTile(QFrame):
    """A folder shown in the main view: up to four thumbnails plus name + count.

    Clicking drills into the folder; right-clicking asks for a context menu.
    Both signals carry the folder's stable key so the view can act on it.
    ``detail`` is what the name doesn't say (a settings folder's prompt and
    settings), shown on hover.
    """

    clicked = pyqtSignal(str)
    context_requested = pyqtSignal(str, QPoint)

    _BADGE = BUTTON_ICON  # on-tile size of the TOC initial

    def __init__(self, key, text, preview_paths, count, favorite=False,
                 context="", badge=None, parent=None):
        super().__init__(parent)
        self._key = key
        self._selected = False
        self.setObjectName("folderTile")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        # The same tile the generations beside it in the flow stand in, plus the
        # breadcrumb line the Favorites collection's tiles carry.
        self.setFixedSize(*tile_shape.folder_tile_size(breadcrumb=bool(context)))
        self.setStyleSheet(tile_shape.idle_css("folderTile"))
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(
            lambda pos: self.context_requested.emit(self._key, self.mapToGlobal(pos))
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(*(tile_shape.TILE_MARGIN,) * 4)
        layout.setSpacing(tile_shape.TILE_SPACING)
        self._thumbnails = self._build_thumbnails(preview_paths)
        layout.addWidget(self._thumbnails)

        if context:
            # Where this folder lives, so a favorited folder is tellable apart from a
            # same-named one elsewhere. Elided from the left to keep the tail — the
            # folder's own parent — visible; the whole path sits in the tooltip.
            crumb = QLabel()
            crumb.setStyleSheet(f"color: {as_hex(TEXT_MUTED)};")
            crumb.setFont(tile_shape.caption_font())
            crumb.setFixedHeight(tile_shape.line_height())
            crumb.setText(crumb.fontMetrics().elidedText(
                context, Qt.TextElideMode.ElideLeft, _INNER_WIDTH))
            crumb.setToolTip(context)
            layout.addWidget(crumb)

        caption_row = QHBoxLayout()
        caption_row.setContentsMargins(0, 0, 0, 0)
        caption_row.setSpacing(GAP_SMALL)
        if badge is not None:
            caption_row.addWidget(self._badge(*badge), 0, Qt.AlignmentFlag.AlignTop)
        self._text = text
        self._caption = caption = QLabel()
        caption.setTextFormat(Qt.TextFormat.RichText)
        caption.setText(self._captioned(favorite))
        caption.setWordWrap(True)
        tile_shape.style_caption(caption)  # the grid's shared caption size
        # A settings folder is named by a code, so what it holds — the prompt and
        # the settings that set it apart — is read on hover rather than under the
        # thumbnails, where it would take more of the tile than the thumbnails do.
        caption.setToolTip(text)
        caption_row.addWidget(caption, 1)
        layout.addLayout(caption_row)

        count_label = QLabel(f"{count} item{'s' if count != 1 else ''}")
        count_label.setStyleSheet(f"color: {as_hex(TEXT_MUTED)};")
        count_label.setFont(tile_shape.caption_font())
        count_label.setFixedHeight(tile_shape.line_height())
        layout.addWidget(count_label)

    @property
    def key(self) -> str:
        return self._key

    def set_favorite(self, favorite: bool) -> None:
        self._caption.setText(self._captioned(favorite))

    def set_selected(self, selected: bool) -> None:
        if selected == self._selected:
            return
        self._selected = selected
        self.setStyleSheet(tile_shape.selected_css("folderTile") if selected
                           else tile_shape.idle_css("folderTile"))

    def _captioned(self, favorite: bool) -> str:
        if not favorite:
            return html.escape(self._text, quote=False)
        return marked_text("star", self._text, color=TEXT_PRIMARY,
                           size=tile_shape.line_height())

    def _badge(self, icon, name: str) -> QLabel:
        badge = QLabel()
        badge.setFixedSize(self._BADGE, self._BADGE)
        badge.setPixmap(icon.pixmap(QSize(self._BADGE, self._BADGE)))
        badge.setToolTip(name)
        return badge

    @staticmethod
    def _build_thumbnails(preview_paths) -> QWidget:
        thumbnails = QWidget()
        thumbnails.setFixedSize(tile_shape.thumbnail_size())
        grid = QGridLayout(thumbnails)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(_CELL_GAP)
        previews = list(preview_paths)[:4]
        if not previews:
            placeholder = QLabel("empty")
            placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
            placeholder.setStyleSheet(
                f"color: {as_hex(TEXT_MUTED)}; background: {palette.EMPTY_PLATE};"
                f" border-radius: {BUTTON_RADIUS}px;")
            placeholder.setFixedSize(tile_shape.thumbnail_size())
            grid.addWidget(placeholder, 0, 0)
            return thumbnails
        for idx in range(4):
            cell = QLabel()
            cell.setFixedSize(*_CELL_SIZE)
            cell.setAlignment(Qt.AlignmentFlag.AlignCenter)
            cell.setStyleSheet(
                f"background: {palette.EMPTY_PLATE}; border-radius: {BUTTON_RADIUS}px;")
            if idx < len(previews):
                pm = QPixmap(str(previews[idx]))
                if not pm.isNull():
                    cell.setPixmap(pm.scaled(
                        *_CELL_SIZE,
                        Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                        Qt.TransformationMode.SmoothTransformation,
                    ))
            grid.addWidget(cell, idx // 2, idx % 2)
        return thumbnails

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self._key)

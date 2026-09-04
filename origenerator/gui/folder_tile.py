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

from origenerator.gui import icons


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

    def __init__(self, key, text, preview_paths, count, starred=False,
                 context="", level=None, detail="", parent=None):
        super().__init__(parent)
        self._key = key
        self.setObjectName("folderTile")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        # A breadcrumb line (used by the Starred shelf) needs a little more height.
        self.setFixedSize(180, 216 if context else 200)
        self.setStyleSheet(
            "#folderTile { border: 1px solid #3f3f3f; border-radius: 4px; }"
            "#folderTile:hover { border-color: #6f6f6f; }"
        )
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(
            lambda pos: self.context_requested.emit(self._key, self.mapToGlobal(pos))
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(4)
        layout.addWidget(self._build_collage(preview_paths))

        if context:
            # Where this folder lives, so a starred folder is tellable apart from a
            # same-named one elsewhere. Elided from the left to keep the tail — the
            # folder's own parent — visible; the whole path sits in the tooltip.
            crumb = QLabel()
            crumb.setStyleSheet("color: #7a7a7a; font-size: 10px;")
            crumb.setFixedHeight(14)
            crumb.setText(crumb.fontMetrics().elidedText(
                context, Qt.TextElideMode.ElideLeft, 164))
            crumb.setToolTip(context)
            layout.addWidget(crumb)

        # The name, led by its recipe-level chip when the folder has one (the same
        # badge the tree shows), so a Starred-shelf tile is placeable even out of
        # its parent's context.
        caption_row = QHBoxLayout()
        caption_row.setContentsMargins(0, 0, 0, 0)
        caption_row.setSpacing(4)
        if level is not None:
            caption_row.addWidget(self._level_badge(level), 0, Qt.AlignmentFlag.AlignTop)
        caption = QLabel(("★ " if starred else "") + text)
        caption.setWordWrap(True)
        caption.setMaximumHeight(30)
        # A settings folder is named by a code, so what it holds — the prompt and
        # the settings that set it apart — is read on hover rather than under the
        # collage, where it would take more of the tile than the pictures do.
        caption.setToolTip(detail or text)
        caption_row.addWidget(caption, 1)
        layout.addLayout(caption_row)

        count_label = QLabel(f"{count} item{'s' if count != 1 else ''}")
        count_label.setStyleSheet("color: #9a9a9a; font-size: 10px;")
        layout.addWidget(count_label)

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
        grid = QGridLayout(collage)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(2)
        previews = list(preview_paths)[:4]
        if not previews:
            placeholder = QLabel("empty")
            placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
            placeholder.setStyleSheet("color: #6a6a6a; background: #2a2a2a; border-radius: 2px;")
            placeholder.setFixedSize(166, 144)
            grid.addWidget(placeholder, 0, 0)
            return collage
        for idx in range(4):
            cell = QLabel()
            cell.setFixedSize(82, 71)
            cell.setAlignment(Qt.AlignmentFlag.AlignCenter)
            cell.setStyleSheet("background: #2a2a2a; border-radius: 2px;")
            if idx < len(previews):
                pm = QPixmap(str(previews[idx]))
                if not pm.isNull():
                    cell.setPixmap(pm.scaled(
                        82, 71,
                        Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                        Qt.TransformationMode.SmoothTransformation,
                    ))
            grid.addWidget(cell, idx // 2, idx % 2)
        return collage

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self._key)

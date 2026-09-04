"""Every version of one image, a row each: its picture, and the facts about it.

An enhancement is a layer, not a replacement: the enhanced file leads the row's
``output_files`` and each earlier one stays listed, so an image can carry several
levels at once — usually one, more when the same image is enhanced again at
different settings to compare them. The preview opens on the most-enhanced
version; this is where the rest are, sitting at the bottom of the info pane
beside the other cross-links (a video's source image, an image's animations).

One level per row, because each is a file with a file's worth to say about it:
the enhancement that made it, where it is on disk (with the copy and
Show-in-Explorer buttons a file row carries anywhere in this app), and when it
was written. That information used to sit in one ``Basic`` block at the top,
pooled under labels naming levels you then had to go and find; it is per
enhancement, so it lives with the enhancement.

A row can also be dragged onto the Enhance subpanel, which absorbs the settings
it carries — the way to say "do that again" about a version you liked without
reading its numbers off and typing them back in.

Levels can be deleted from here: pick rows and press Delete or Backspace, or
right-click for the menu. A binned version is a file, not a generation — the
image keeps its folder, its star and its other versions — and the delete is
undoable like every other. What is refused is emptying the row: an image with no
file left is a deleted generation, and that is the gallery's own delete.

An enhancement still cooking takes the ``+ Enhance`` row's own slot at the head
of the list, mirroring the run's streamed frames the way the in-flight cards do
everywhere else — the row becomes the thing it asked for, and the level being
made appears where the level will be.

The list is up for every image, even one with nothing but its original: it is
where an image's versions live, and a place that appears only once you already
have versions is a place you never find. It also closes with a ``+ Enhance``
row that makes another at the current settings — dimmed when the image already
holds one made at exactly those, and hovering the dimmed row lights the level
it would have duplicated.
"""

import json

from PyQt6.QtCore import QByteArray, QMimeData, QPoint, Qt, pyqtSignal
from PyQt6.QtGui import QDrag, QPixmap
from PyQt6.QtWidgets import (
    QApplication,
    QGraphicsOpacityEffect,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMenu,
    QVBoxLayout,
    QWidget,
)

from origenerator.generation_metadata import MetaItem, created_item, file_item
from origenerator.gui.collapsible_section import CollapsibleSection
from origenerator.gui.drag_thumbnail import fit_thumbnail, set_drag_thumbnail
from origenerator.gui.metadata_block import label_column_width, meta_cells

# A dragged enhancement level carries the params that produced it under this
# type; the Enhance subpanel reads it to absorb those settings.
ENHANCE_LEVEL_MIME = "application/x-origenerator-enhance-level"

_TILE = 96  # the thumbnail box; the level's facts sit beside it
# The in-flight edge the Recents shelf's cards wear, so work in progress reads
# the same wherever it shows.
_PENDING_BORDER = "2px solid #3080e0"
# The dashed box of an empty slot waiting to be filled, and the lit edge a level
# wears while the row that would duplicate it is hovered.
_ADD_BORDER = "1px dashed #808080"
_MATCH_BORDER = "2px solid #30a030"
# Which grid column a fact's value sits in: the one that stretches, and the one
# cell of a line that fills its height rather than sitting at the top of it.
_VALUE_COLUMN = 1
# Every key a row can carry. Each row is its own grid, so its key column would
# otherwise size to its own longest key — and the values would step in and out
# down the list as rows gain or lose the Enhancement line (the original has
# none). Sized to the widest of these, they line up all the way down.
_FACT_KEYS = ("Enhancement", "File", "Created")
# A picked row lightens, the way a picked thumbnail does — same fill, so "this
# one is selected" reads the same in both places. The labels have to be made
# transparent for it to show at all: the app's global ``QWidget`` background
# paints every one of them opaque over whatever the row fills with, and the fill
# would otherwise appear only in the gaps between them.
_ROW_CSS = "#levelRow QLabel { background-color: transparent; }"
_SELECTED_ROW_CSS = (
    "#levelRow { background-color: #3a3a3a; border-radius: 4px; }" + _ROW_CSS
)


def enhance_level_mime(params: dict) -> QMimeData:
    """The drag payload carrying one level's enhancement settings."""
    mime = QMimeData()
    mime.setData(ENHANCE_LEVEL_MIME,
                 QByteArray(json.dumps(params).encode("utf-8")))
    return mime


def params_from_mime(mime) -> dict | None:
    """The settings a dragged level carries, or ``None`` for any other drag."""
    if not mime.hasFormat(ENHANCE_LEVEL_MIME):
        return None
    try:
        params = json.loads(bytes(mime.data(ENHANCE_LEVEL_MIME)).decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    return params if isinstance(params, dict) else None


def _pass_mouse_through(widget) -> None:
    """Let clicks, hovers and right-clicks on this child reach the row it is in.

    A row is one thing to click — anywhere on it picks that version — but its
    picture and its lines of text cover nearly all of it, and a child widget
    takes the press by default. That left only the margins around them live.

    It also settles which context menu a right-click gets. The value labels come
    from the metadata block, where they are selectable text, and Qt gives
    selectable text its own Copy / Select All menu; over a version that menu is
    both meaningless (there is a Copy button on the row, for the one value worth
    copying) and in the way of the row's own Delete.
    """
    widget.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
    widget.setContextMenuPolicy(Qt.ContextMenuPolicy.NoContextMenu)


class _Row(QWidget):
    """The shape every entry in the list shares: a picture, then a bold title
    over a column of ``label: value`` facts.

    One shape for the finished levels, the one being made, and the card that
    would make another — so a run in flight sits in the list reading like the
    level it is about to become rather than like a different kind of thing."""

    def __init__(self, title: str, parent=None):
        super().__init__(parent)
        self.setObjectName("levelRow")
        # Without this a stylesheet background on a plain QWidget paints nothing
        # at all, so the selection fill would never show.
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet(_ROW_CSS)
        # Two layouts, not one: the picture and the facts sit side by side while
        # there is room for both, and the facts drop underneath the picture when
        # there is not — see :meth:`_reflow`. A row that could only sit side by
        # side would be the widest thing in the tab, and would decide how narrow
        # the whole pane could be dragged before its settings scrolled sideways.
        self._column = QVBoxLayout(self)
        self._column.setContentsMargins(2, 2, 2, 2)
        self._column.setSpacing(6)
        box = QHBoxLayout()
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(8)
        self._column.addLayout(box)
        self._beside = box
        self._wrapped = False
        self._picture = QLabel()
        self._picture.setFixedSize(_TILE, _TILE)
        self._picture.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._picture.setWordWrap(True)
        _pass_mouse_through(self._picture)
        box.addWidget(self._picture, 0, Qt.AlignmentFlag.AlignTop)
        # A grid rather than a row of rows: a container widget per fact would
        # take every click landing on it, and Qt's hit test skips a container
        # marked transparent along with the buttons inside it — so there would be
        # no arrangement of that shape where both the row and its buttons are
        # clickable. Laid straight into the grid, the only children are labels
        # (which pass clicks through) and the buttons themselves. The columns
        # line the keys up across the facts for free.
        facts = QGridLayout()
        facts.setContentsMargins(0, 0, 0, 0)
        facts.setHorizontalSpacing(8)
        facts.setVerticalSpacing(3)
        facts.setColumnStretch(_VALUE_COLUMN, 1)
        self._title = QLabel(title)
        self._title.setStyleSheet("font-weight: 600; background: transparent;")
        _pass_mouse_through(self._title)
        facts.addWidget(self._title, 0, 0, 1, 4)
        self._facts = facts
        self._fact_cells: list[QWidget] = []
        box.addLayout(facts, 1)

    def minimumSizeHint(self):
        """As narrow as the row gets — which is the wrapped arrangement's width,
        whichever one it is in at the moment: the facts can always drop below the
        picture, so the pair's widths never add up."""
        hint = super().minimumSizeHint()
        margins = self._column.contentsMargins()
        widest = max(self._picture.minimumSizeHint().width(),
                     self._facts.minimumSize().width())
        hint.setWidth(widest + margins.left() + margins.right())
        return hint

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._reflow(event.size().width())

    def _reflow(self, width: int) -> None:
        """Put the facts beside the picture or underneath it, by whether both fit."""
        margins = self._column.contentsMargins()
        beside = (self._picture.sizeHint().width() + self._beside.spacing()
                  + self._facts.minimumSize().width()
                  + margins.left() + margins.right())
        wrapped = width < beside
        if wrapped == self._wrapped:
            return
        if wrapped:
            self._beside.removeItem(self._facts)
            self._column.addItem(self._facts)
        else:
            self._column.removeItem(self._facts)
            self._beside.addLayout(self._facts, 1)
        self._wrapped = wrapped
        self.updateGeometry()   # the row is a different height in each shape

    def _show_facts(self, items: list[MetaItem]) -> None:
        """Lay this row's facts out as the same ``label: value`` cells a metadata
        block builds — so the enhancement that made a version, the file it wrote
        and when it was written all read alike, and the file line keeps its copy
        and Show-in-Explorer buttons. Replaces whatever was there."""
        for widget in self._fact_cells:
            self._facts.removeWidget(widget)
            widget.setParent(None)
            widget.deleteLater()
        self._fact_cells = []
        key_width = label_column_width([MetaItem(key, "") for key in _FACT_KEYS])
        for line, item in enumerate(items, start=1):
            for column, widget in enumerate(meta_cells(item, key_width)):
                if widget is None:
                    continue
                if isinstance(widget, QLabel):
                    _pass_mouse_through(widget)
                # The value fills its cell so it can wrap; a key and a button sit
                # at the top of a line the value has grown taller than.
                if column == _VALUE_COLUMN:
                    self._facts.addWidget(widget, line, column)
                else:
                    self._facts.addWidget(widget, line, column,
                                          Qt.AlignmentFlag.AlignTop)
                self._fact_cells.append(widget)

    def _show_picture(self, pixmap: QPixmap) -> None:
        self._picture.setPixmap(pixmap.scaled(
            _TILE, _TILE,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        ))


class _LevelRow(_Row):
    """One version: its picture, the enhancement that made it, its file and when
    that file was written.

    Clicking puts it in the preview and picks it; dragging it carries those
    settings for the Enhance subpanel to absorb.
    """

    clicked = pyqtSignal(int, Qt.KeyboardModifier)
    context_requested = pyqtSignal(int, QPoint)

    def __init__(self, level, position: int, image_path, created_fallback: str = "",
                 held_days: int | None = None, parent=None):
        super().__init__(level.label, parent)
        self._position = position
        self._params = dict(level.params)
        self._press_pos = None
        self._selected = False
        pixmap = QPixmap(str(image_path)) if image_path else QPixmap()
        # The picture that trails the cursor when this row is dragged, cut once
        # from the file rather than from the 96px tile — the same box every other
        # drag in the app trails.
        self._drag_picture = fit_thumbnail(pixmap)
        if not pixmap.isNull():
            self._show_picture(pixmap)
        else:
            # The file is gone (trashed, or moved out from under us). The level
            # still lists — its facts say which one it was — so the box shows
            # the em dash the rest of the app uses for "nothing to show here".
            self._picture.setText("—")
            self._picture.setToolTip("This version's file is no longer on disk")
        items = []
        if level.settings:
            items.append(MetaItem("Enhancement", level.settings))
        items.append(file_item(level.file, held_days=held_days))
        items.append(created_item(level.file, created_fallback))
        self._show_facts(items)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.ClickFocus)  # so Delete reaches the list
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(
            lambda pos: self.context_requested.emit(
                self._position, self.mapToGlobal(pos))
        )
        self.setToolTip(
            f"{level.settings}\nDrag onto Enhance to reuse these settings"
            if level.params else level.label
        )

    def position(self) -> int:
        return self._position

    def is_selected(self) -> bool:
        return self._selected

    def set_selected(self, selected: bool) -> None:
        if selected == self._selected:
            return
        self._selected = selected
        self.setStyleSheet(_SELECTED_ROW_CSS if selected else _ROW_CSS)

    def set_highlighted(self, on: bool) -> None:
        """Light this level's picture — what the ``+ Enhance`` row points at
        when it is dimmed because this is the version it would duplicate."""
        self._picture.setStyleSheet(
            f"border: {_MATCH_BORDER}; border-radius: 3px;" if on else ""
        )

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._press_pos = event.position().toPoint()

    def mouseMoveEvent(self, event):
        # Only a level that knows its settings is worth dragging: the original
        # was made by no enhancement, so there is nothing for the panel to take.
        if self._press_pos is None or not self._params:
            return
        moved = (event.position().toPoint() - self._press_pos).manhattanLength()
        if moved < QApplication.startDragDistance():
            return  # still a click, not yet a drag — a thumbnail's own threshold
        self._press_pos = None
        drag = QDrag(self)
        drag.setMimeData(enhance_level_mime(self._params))
        set_drag_thumbnail(drag, self._drag_picture)  # the version's image trails the cursor
        drag.exec(Qt.DropAction.CopyAction)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self._press_pos is not None:
            self._press_pos = None
            self.clicked.emit(self._position, event.modifiers())


class _PendingRow(_Row):
    """The enhancement being made right now: its live frame, or the stage it's at.

    Wears the same blue "in progress" edge as the Recents shelf's in-flight
    cards, so a level under construction reads the same here as work in flight
    reads anywhere else in the app.
    """

    def __init__(self, parent=None):
        super().__init__("Enhancing", parent)
        self._picture.setStyleSheet(
            f"background-color: transparent; border: {_PENDING_BORDER};"
            " border-radius: 3px;"
        )
        # The settings row a finished level carries, in the same place: what is
        # being made is as much a question of "at what" as the levels already
        # there, and it is the only place to read it back before the run lands.
        # No file and no timestamp yet — that is exactly what is still cooking.
        self._settings = ""
        self.setToolTip("An enhancement of this image is being generated")

    def update_pending(self, status: str, frame: bytes | None, settings: str = ""):
        pixmap = QPixmap()
        if frame and pixmap.loadFromData(frame) and not pixmap.isNull():
            self._show_picture(pixmap)
        else:
            self._picture.setText(
                "Generating…" if status == "running" else "Queued…"
            )
        # Only when the text actually moves: a run streams several frames a
        # second and each would otherwise rebuild the row under the cursor.
        if settings != self._settings:
            self._settings = settings
            self._show_facts([MetaItem("Enhancement", settings)] if settings else [])
        self.setToolTip(
            f"An enhancement of this image is being generated at {settings}"
            if settings else "An enhancement of this image is being generated"
        )


class _AddRow(_Row):
    """The ``+ Enhance`` slot that leads the list.

    Live, it makes another version at whatever the Enhance panel currently says.
    Dimmed, the image already holds one made at exactly those settings, and
    hovering it lights that level rather than leaving you to compare numbers —
    the answer to "why can't I press this" is the row it points at.
    """

    clicked = pyqtSignal()
    hovered = pyqtSignal(bool)

    def __init__(self, settings: str, duplicate_of: int | None, parent=None):
        super().__init__("Enhance", parent)
        self._enabled = duplicate_of is None
        self._picture.setText("+")
        self._picture.setStyleSheet(
            f"border: {_ADD_BORDER}; border-radius: 3px; font-size: 28px;"
        )
        if settings:
            self._show_facts([MetaItem("Enhancement", settings)])
        # Dimmed by opacity rather than by setEnabled: Qt delivers no mouse
        # events to a disabled widget, and the hover is exactly what the dimmed
        # state is for — it is how the row explains why it cannot be pressed.
        if not self._enabled:
            effect = QGraphicsOpacityEffect(self)
            effect.setOpacity(0.4)
            self.setGraphicsEffect(effect)
        self.setCursor(Qt.CursorShape.PointingHandCursor if self._enabled
                       else Qt.CursorShape.ForbiddenCursor)
        self.setToolTip(
            f"Enhance this image at {settings}" if self._enabled
            else "This image already has a version at exactly these settings"
        )

    def enterEvent(self, event):
        self.hovered.emit(True)
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.hovered.emit(False)
        super().leaveEvent(event)

    def mouseReleaseEvent(self, event):
        if self._enabled and event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()


class EnhanceVersions(QWidget):
    """The levels of one image, newest first, one per row.

    ``show_levels`` takes :class:`~origenerator.gallery.enhance.EnhanceLevel`
    objects (as :func:`~origenerator.gallery.enhance.displayed_levels` produces
    them) paired with the on-disk file to draw, plus the ``(status, frame)`` of
    an enhancement still running on this image. Clicking a level's row emits
    ``level_selected`` with its position in that list, for the panel to put in
    the preview; picking rows and pressing Delete (or the right-click menu's
    Delete) emits ``delete_requested`` with those positions.
    """

    level_selected = pyqtSignal(int)
    enhance_requested = pyqtSignal()   # the "+ Enhance" row was pressed
    delete_requested = pyqtSignal(list)  # positions of the levels to bin

    def __init__(self, parent=None):
        super().__init__(parent)
        box = QVBoxLayout(self)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(4)
        # A foldable section like the form's above it: this pane is one column
        # of collapsible groups, and a heading that cannot fold reads as the one
        # thing you are not allowed to put away.
        self._section = CollapsibleSection("Enhancement levels")
        box.addWidget(self._section)
        self._host = QWidget()
        QVBoxLayout(self._host)
        self._section.content_form().addRow(self._host)
        self._pending: _PendingRow | None = None
        self._rows: list[_LevelRow] = []
        self.hide()

    def is_collapsed(self) -> bool:
        return self._section.is_collapsed()

    def set_collapsed(self, collapsed: bool) -> None:
        self._section.set_collapsed(collapsed)

    def show_levels(self, items: list[tuple], pending: tuple | None = None,
                    add: tuple | None = None, created_fallback: str = "",
                    held_days: int | None = None):
        """Rebuild the list from ``(level, image_path)`` pairs.

        ``add`` is ``(settings, duplicate_of)`` for the ``+ Enhance`` row, which
        leads the list: that is where a new version arrives, since the list runs
        newest first. ``duplicate_of`` names the level those settings would
        duplicate, or ``None`` when they would make something new.

        ``pending`` is the ``(status, frame, settings)`` of an enhancement still
        running, and it takes that same leading slot — the row *becomes* the
        thing it asked for rather than sitting beside it, which is what the press
        looks like from the other side.

        ``created_fallback`` stands in on a level whose file is no longer on disk
        to be asked when it was written — the row's own timestamp, which is the
        closest true answer left.

        ``held_days`` is set only for a deleted image, and each level's File line
        leads with how long it has been in the trash.

        Hidden only when there is nothing at all to show — no versions, nothing
        running, and no row to press, which is what a video looks like.
        """
        # Replace the host wholesale — the same delete-and-rebuild idiom the
        # related-media strips use, so no row outlives the levels it described.
        form = self._section.content_form()
        form.removeRow(self._host)
        self._host = QWidget()
        column = QVBoxLayout(self._host)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(6)
        self._pending = None
        self._rows = []
        # One leading slot, held by whichever of the two applies: the run in
        # flight if there is one, else the row that would start it.
        if pending is not None:
            self._pending = _PendingRow()
            self._pending.update_pending(*pending)
            column.addWidget(self._pending)
        elif add is not None:
            settings, duplicate_of = add
            card = _AddRow(settings, duplicate_of)
            card.clicked.connect(self.enhance_requested)
            card.hovered.connect(
                lambda on, at=duplicate_of: self._highlight_level(at, on))
            column.addWidget(card)
        for position, (level, image_path) in enumerate(items):
            row = _LevelRow(level, position, image_path, created_fallback, held_days)
            row.clicked.connect(self._on_row_clicked)
            row.context_requested.connect(self._on_row_menu)
            self._rows.append(row)
            column.addWidget(row)
        form.addRow(self._host)
        self.setVisible(bool(items) or pending is not None or add is not None)

    # --- picking levels, and binning the picked ones ------------------------

    def selected_positions(self) -> list[int]:
        """The levels currently picked, in list order."""
        return [row.position() for row in self._rows if row.is_selected()]

    def _on_row_clicked(self, position: int, modifiers):
        """Pick a level and put it in the preview.

        Ctrl adds to the picking without moving the preview — the gesture is
        "these ones", aimed at the Delete that follows, and swapping the picture
        under each ctrl-click would fight it."""
        if modifiers & Qt.KeyboardModifier.ControlModifier:
            for row in self._rows:
                if row.position() == position:
                    row.set_selected(not row.is_selected())
            return
        for row in self._rows:
            row.set_selected(row.position() == position)
        self.level_selected.emit(position)

    def _on_row_menu(self, position: int, global_pos: QPoint):
        """The right-click menu: Delete, over whatever is picked.

        A right-click on an unpicked row picks it first, so the menu always acts
        on what it appeared over — the same rule the thumbnail menu follows."""
        if position not in self.selected_positions():
            for row in self._rows:
                row.set_selected(row.position() == position)
        picked = self.selected_positions()
        if not picked:
            return
        menu = QMenu(self)
        action = menu.addAction(
            f"Delete {len(picked)} version{'s' if len(picked) != 1 else ''}"
        )
        if not self._may_delete(picked):
            # Grayed with the reason on it rather than absent: the answer to
            # "why can't I delete this" is the only thing the menu can offer.
            action.setEnabled(False)
            action.setText("Delete (this is the image's only version)")
        if menu.exec(global_pos) is action and self._may_delete(picked):
            self.delete_requested.emit(picked)

    def _may_delete(self, positions: list[int]) -> bool:
        """Whether binning ``positions`` would leave the image a version.

        An image with no file left is a deleted generation, and deleting a
        generation is the gallery's own action, reached from its thumbnail — a
        version list quietly doing it would be a much bigger delete than the one
        that was asked for."""
        return bool(positions) and len(positions) < len(self._rows)

    def keyPressEvent(self, event):
        """Delete or Backspace bins the picked levels — the keys that delete a
        picked thumbnail, over the picked versions instead."""
        if event.key() in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace):
            picked = self.selected_positions()
            if self._may_delete(picked):
                self.delete_requested.emit(picked)
                return
        super().keyPressEvent(event)

    def _highlight_level(self, position: int | None, on: bool) -> None:
        """Light the level the dimmed ``+ Enhance`` row would have duplicated."""
        if position is None or not 0 <= position < len(self._rows):
            return
        self._rows[position].set_highlighted(on)

    def update_pending(self, pending: tuple | None) -> bool:
        """Feed a new frame to the row already standing, without rebuilding.

        A run streams frames several times a second, and rebuilding the list on
        each would thrash the layout under the cursor mid-drag. Returns whether
        the update landed; ``False`` means the list's shape has to change (a run
        started or ended) and the caller should rebuild.
        """
        if (self._pending is None) != (pending is None):
            return False
        if pending is not None:
            self._pending.update_pending(*pending)
        return True

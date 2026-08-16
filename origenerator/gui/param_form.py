import random
from pathlib import Path
from typing import Callable

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QStackedWidget,
    QPlainTextEdit, QLineEdit, QSpinBox, QDoubleSpinBox,
    QComboBox, QPushButton, QToolButton, QFileDialog,
)
from PyQt6.QtCore import Qt, QEvent, pyqtSignal

from origenerator.config import COMFYUI_INPUT_DIR
from origenerator.gui.collapsible_section import CollapsibleSection
from origenerator.gui.copy_button import CopyButton
from origenerator.gui.no_wheel import NoWheelComboBox, NoWheelDoubleSpinBox, NoWheelSpinBox
from origenerator.gui import param_sections
from origenerator.gui.param_help import param_help
from origenerator.paths import ensure_shared_ui_on_path
from origenerator.workflows.base import ParamDef
from origenerator.workflows.derived_size import override_size

ensure_shared_ui_on_path()
from shared_ui.check_box import CheckBox

_SEED_MAX = (1 << 63) - 1

# The locked-dimension spinboxes span from a stride floor up past any realistic
# derived or overridden size; 0 is reserved as "no size known yet" (shown as the
# em dash) for a workflow whose input image can't be measured.
_DIMENSION_MAX = 8192
_DIMENSION_STEP = 16
# The unlock toggle's face: a closed padlock while the derived size is locked, an
# open one once the user has unlocked it to override.
_LOCK_CLOSED = "🔒"
_LOCK_OPEN = "🔓"
# The padlock renders at this point size regardless of the form's (larger) font,
# so it stays a compact icon toggle and its width is predictable.
_UNLOCK_FONT_PT = 11

# Zero-width spaces / joiners / BOM that can ride invisibly on a pasted path.
# The metadata block inserts zero-width spaces into displayed paths for on-screen
# wrapping, so text copied from there carries them; none belongs in a real path.
# U+200B ZWSP, U+200C ZWNJ, U+200D ZWJ, U+2060 word-joiner, U+FEFF BOM.
_INVISIBLE = dict.fromkeys((0x200B, 0x200C, 0x200D, 0x2060, 0xFEFF), None)


def _clean_image_ref(value: str) -> str:
    """A ``LoadImage`` path with invisible wrapping characters and stray
    surrounding whitespace stripped, so a value that looks right actually
    resolves against ComfyUI's input folder (or as an absolute path)."""
    return value.translate(_INVISIBLE).strip()


def _is_copyable(pd: ParamDef) -> bool:
    """Which fields earn a copy-to-clipboard button: the seeds (the value most
    often lifted to reproduce a result) and the prompts (long multiline text).
    The plain scalars — steps, cfg, dimensions — are quick enough to retype."""
    return pd.type == "seed" or (pd.type == "str" and pd.multiline)


def _select_combo_value(combo: QComboBox, value: str):
    """Show ``value`` in ``combo``, offering it as a new option if it isn't one.

    A workflow default or a reused choice (e.g. a LoRA whose file is gone) may
    not be among the scanned options; adding it keeps the combo faithful to the
    value it was given instead of snapping to whatever sorts first.
    """
    idx = combo.findText(value)
    if idx < 0:
        combo.addItem(value)
        idx = combo.findText(value)
    combo.setCurrentIndex(idx)


class ParamForm(QWidget):
    """The editable settings for one workflow, grouped into collapsible sections.

    A workflow's :meth:`~origenerator.workflows.base.WorkflowTemplate.
    param_definitions` gives the fields; they're laid out by the canonical order
    in :mod:`origenerator.gui.param_sections` — not the workflow's own declaration
    order — so every workflow presents the same kinds of settings in the same
    sections, in the same place. Params a config carries but this workflow lays no
    field for (its hidden VAE/CLIP, an import's extras) round-trip untouched and
    show as read-only rows dropped into the matching section.

    ``hidden_keys`` are params this form deliberately doesn't present at all —
    no field, no read-only row, and no value absorbed from a loaded config: they
    are pinned at the workflow's own defaults, so what the form emits for them
    is always the same. This is how the enhance params stay off a form whose
    every other setting decides which gallery folder a run lands in. They belong
    to the Enhance subpanel, which applies enhancement as a separate layer — and
    pinning them is what stops a Generate seeded from an old enhanced run coming
    out enhanced again with the subpanel's box unticked.
    """

    changed = pyqtSignal()          # any field's value changed

    def __init__(
        self,
        param_defs: list[ParamDef],
        parent=None,
        *,
        size_deriver: Callable[[dict], tuple[int, int] | None] | None = None,
        hidden_keys: tuple[str, ...] = (),
    ):
        super().__init__(parent)
        # Params carried but never shown, pinned at the definitions' own defaults
        # — a loaded config never moves them (see the class docstring).
        self._hidden_keys = frozenset(hidden_keys)
        self._hidden = {
            pd.key: pd.default for pd in param_defs if pd.key in self._hidden_keys
        }
        # When set (an i2v workflow), the output size is derived from the input
        # image: the form shows a locked width/height pair filled from this
        # callable, which the user can unlock to override. ``None`` for a
        # manual-size or size-less workflow, leaving the Dimensions section to the
        # workflow's own width/height params (if any).
        self._size_deriver = size_deriver
        # The unlock toggle and hint for the derived-size pair, built only in
        # derived mode. ``None`` otherwise. The toggle floats between the width and
        # height rows like the swap button, so it links the pair without shrinking
        # either field.
        self._unlock_btn: QToolButton | None = None
        self._dimensions_hint: QLabel | None = None
        # Per derived dimension: the editable spinbox (in ``_widgets``), the plain
        # value label shown while locked, and the stack that swaps between them.
        self._dim_value_labels: dict[str, QLabel] = {}
        self._dim_stacks: dict[str, QStackedWidget] = {}
        self._widgets: dict[str, QWidget] = {}
        self._randomize_checks: dict[str, CheckBox] = {}
        self._browse_buttons: dict[str, QPushButton] = {}
        # Copy-to-clipboard buttons on the fields worth lifting whole — the prompts
        # and the seeds, the read-only inspect pane's copy targets before it merged
        # into this editable form.
        self._copy_buttons: dict[str, CopyButton] = {}
        # A single swap-width-and-height button, built only when the workflow has
        # both dimension params (t2i does; i2v derives its size in-graph). None
        # when absent, so callers can tell whether the control exists. It floats as
        # a free child of the Dimensions section, so it folds away with it.
        self._swap_dimensions_btn: QPushButton | None = None
        self._width_label: QWidget | None = None
        self._height_label: QWidget | None = None
        # Params a config carries but this form has no widget for — the workflow's
        # remaining hidden settings (VAE, CLIP…), or an import's extras. The form
        # round-trips whatever value it was given (so reusing a generation
        # reproduces them) and shows them as read-only rows in the matching section.
        self._passthrough: dict = {}
        # The read-only rows currently rendered: (section title, key, value label),
        # so a later set_values can drop them cleanly and re-place the new ones.
        self._readonly_rows: list[tuple[str, str, QLabel]] = []
        # Every section, in display order, built up front (even those a fresh form
        # leaves empty) so a passthrough-only section still appears in its fixed
        # place once a config supplies it.
        self._sections: dict[str, CollapsibleSection] = {}
        self._section_order: list[str] = []
        # The keys currently occupying each section, in row order — editable fields
        # plus any read-only rows — so a passthrough row inserts at its canonical
        # slot rather than merely appending after the editable fields.
        self._present_keys: dict[str, list[str]] = {}
        self._param_defs = [pd for pd in param_defs if pd.key not in self._hidden_keys]
        self._build(self._param_defs)

    def _build(self, defs: list[ParamDef]):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(10)

        specs = [(s.title, s.collapsed) for s in param_sections.SECTIONS]
        specs.append((param_sections.OTHER_TITLE, param_sections.OTHER_COLLAPSED))
        for title, collapsed in specs:
            section = CollapsibleSection(title, collapsed=collapsed)
            section.toggled.connect(self._position_dimension_controls)
            self._sections[title] = section
            self._present_keys[title] = []
            self._section_order.append(title)
            outer.addWidget(section)
        outer.addStretch(1)  # collect any slack at the bottom, not between sections

        # Fields in canonical order, so the workflow's own declaration order can't
        # reshuffle where a setting lands.
        for pd in sorted(defs, key=lambda d: param_sections.key_rank(d.key)):
            widget = self._make_widget(pd)
            self._widgets[pd.key] = widget
            self._wire_changed(widget)
            self._add_row(pd.key, pd.label, self._field_cell(pd, widget))
        self._build_swap_button()
        self._build_derived_dimensions()
        self._refresh_section_visibility()

    def _add_row(self, key: str, label: str, field):
        """Insert one row (a field cell or a read-only value) into its section at
        the canonical position among the rows already there. ``field`` is a
        ``QWidget`` or a ``QLayout`` (a field paired with its trailing controls).

        The row's help (see :mod:`origenerator.gui.param_help`) goes on its label
        as well as its input: the label is what you are looking at when you
        wonder what a setting is, and hovering the word is the natural move."""
        title = param_sections.section_title(key)
        keys = self._present_keys[title]
        index = self._insert_index(keys, key)
        form = self._sections[title].content_form()
        form.insertRow(index, label, field)
        keys.insert(index, key)
        help_text = param_help(key)
        if help_text:
            label_widget = form.itemAt(index, form.ItemRole.LabelRole)
            if label_widget is not None and label_widget.widget() is not None:
                label_widget.widget().setToolTip(help_text)
            widget = self._widgets.get(key)
            if widget is not None:
                widget.setToolTip(help_text)

    @staticmethod
    def _insert_index(present: list[str], key: str) -> int:
        """The row index ``key`` belongs at among ``present`` (kept in canonical
        order): the count of present keys that rank before it."""
        rank = param_sections.key_rank(key)
        return sum(1 for k in present if param_sections.key_rank(k) < rank)

    def _refresh_section_visibility(self):
        """Show a section iff it holds any row; empty ones take no space. Then
        re-place the floating dimension control, since the sections above it may
        have moved."""
        for title, section in self._sections.items():
            section.setVisible(bool(self._present_keys[title]))
        self._position_dimension_controls()

    def _field_cell(self, pd: ParamDef, widget: QWidget):
        """The input, optionally paired with trailing controls.

        The copy button leads (just right of the input), then the Random checkbox
        (seed) or Browse button (image). Each sits in a shared cell so the label
        column stays aligned across every row. Next to a tall multiline prompt the
        copy button hugs the top corner; next to a single-line seed it centers so
        it lines up with the checkbox beside it.
        """
        extras = self._make_extras(pd)
        if not extras:
            return widget
        cell = QHBoxLayout()
        cell.setContentsMargins(0, 0, 0, 0)
        cell.addWidget(widget, 1)
        multiline = isinstance(widget, QPlainTextEdit)
        for extra in extras:
            if isinstance(extra, CopyButton) and multiline:
                cell.addWidget(extra, 0, Qt.AlignmentFlag.AlignTop)
            else:
                cell.addWidget(extra)
        return cell

    def _make_extras(self, pd: ParamDef) -> list[QWidget]:
        # Copy leads so it reads [field] [copy] [Random]/[Browse].
        extras: list[QWidget] = []
        if _is_copyable(pd):
            copy = CopyButton(lambda key=pd.key: self._field_text(key))
            self._copy_buttons[pd.key] = copy
            extras.append(copy)
        if pd.type == "seed":
            cb = CheckBox("Random")
            cb.setChecked(True)
            cb.toggled.connect(self.changed)
            self._randomize_checks[pd.key] = cb
            extras.append(cb)
        if pd.type == "image":
            browse = QPushButton("Browse...")
            browse.clicked.connect(
                lambda _checked=False, key=pd.key: self._browse_image(key)
            )
            self._browse_buttons[pd.key] = browse
            extras.append(browse)
        return extras

    def _field_text(self, key: str) -> str:
        """The field's current on-screen text, for its copy button — a live read
        at click time, so a just-typed prompt or seed is what lands on the
        clipboard."""
        w = self._widgets[key]
        if isinstance(w, QPlainTextEdit):
            return w.toPlainText()
        return w.text()

    def _has_param(self, key: str) -> bool:
        return any(pd.key == key for pd in self._param_defs)

    def _build_swap_button(self):
        """Add a swap-width-and-height button when the form has both dimensions.

        It floats in a gutter opened to the left of the two labels, midway between
        their rows, so it reads as linking the pair rather than trailing either
        field. As a free child of the Dimensions section's content (not a form
        cell) it folds away with the section and needs manual placement — see
        :meth:`_position_swap_button`. Absent for a workflow that derives its size
        in-graph (i2v) and so has no dimensions to swap.
        """
        if not (self._has_param("width") and self._has_param("height")):
            return
        content = self._sections["Dimensions"].content()
        btn = QPushButton("⇅", content)  # ⇅ up/down arrows: swap the stacked pair
        btn.setToolTip("Swap width and height")
        btn.clicked.connect(self.swap_dimensions)
        btn.adjustSize()
        self._swap_dimensions_btn = btn
        form = self._sections["Dimensions"].content_form()
        self._width_label = form.labelForField(self._widgets["width"])
        self._height_label = form.labelForField(self._widgets["height"])
        # The section's content lays its rows out on its own resize/show; follow
        # those so the free-floating button tracks them even when it unfolds.
        content.installEventFilter(self)

    def _position_swap_button(self):
        """Center the swap button between the width and height rows, inside a left
        gutter reserved for it so it sits clear of the "Width"/"Height" labels.

        The gutter is the section's left margin, sized to the button here (its
        final width isn't known until its font and stylesheet apply, after
        construction) — the same lane the unlock toggle opens on a derived-size
        form. Squeezing the button into whatever space the labels happened to
        leave is what put it on top of the words. In the Dimensions content's
        coordinates, its parent; called on every resize/show/toggle since a free
        child gets no help from the layout, and a no-op while the section is
        folded (the button hides with it).
        """
        btn = self._swap_dimensions_btn
        if btn is None or self._sections["Dimensions"].is_collapsed():
            return
        btn.adjustSize()
        gutter = btn.width() + 10  # room for the button plus a gap to the labels
        form = self._sections["Dimensions"].content_form()
        if form.contentsMargins().left() != gutter:
            # Push the labels over to open the gutter; the relayout re-invokes us
            # with the rows in their new positions.
            form.setContentsMargins(gutter, 2, 0, 4)
            return
        top = self._widgets["width"].geometry()
        bottom = self._widgets["height"].geometry()
        y = (top.center().y() + bottom.center().y()) // 2 - btn.height() // 2
        btn.move(max(0, (gutter - btn.width()) // 2), y)
        btn.raise_()

    def eventFilter(self, obj, event):
        # Installed on the Dimensions content: re-place the floating control (swap
        # or unlock) whenever that content relays out (unfolding, or widening).
        if event.type() in (QEvent.Type.Resize, QEvent.Type.Show):
            self._position_dimension_controls()
        return super().eventFilter(obj, event)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._position_dimension_controls()

    def showEvent(self, event):
        super().showEvent(event)
        self._position_dimension_controls()

    def _position_dimension_controls(self):
        """Re-place whichever free-floating control the Dimensions section carries:
        the swap button (manual-size workflow) or the unlock toggle (derived-size
        workflow). Each no-ops when its control is absent, so this is safe to call
        from every relayout hook regardless of which kind of form this is."""
        self._position_swap_button()
        self._position_unlock_button()

    def swap_dimensions(self):
        """Exchange the width and height field values."""
        width, height = self._widgets["width"], self._widgets["height"]
        w, h = width.value(), height.value()
        width.setValue(h)
        height.setValue(w)

    # --- derived dimensions: the input-image size, shown locked & unlockable ---

    def _build_derived_dimensions(self):
        """For a size-deriving workflow, add a width/height pair to the Dimensions
        section that reads as plain values while locked (like the read-only
        passthrough rows — "864", not an input box) and turns into editable
        spinboxes when unlocked. A floating padlock toggle, centered between the
        two rows in a reserved left gutter so it clears the labels, does the
        unlocking. A no-op for a workflow that sets its size by hand (its own
        width/height params already fill this section) or has none.
        """
        if self._size_deriver is None:
            return
        for key, label_text in (("width", "Width"), ("height", "Height")):
            box = NoWheelSpinBox()
            box.setMinimum(0)  # 0 == "size not yet known", shown as the em dash
            box.setMaximum(_DIMENSION_MAX)
            box.setSingleStep(_DIMENSION_STEP)
            box.setSpecialValueText("—")
            box.valueChanged.connect(self.changed)
            self._widgets[key] = box
            value_label = QLabel("—")
            value_label.setObjectName("readonlyParamValue")  # match the passthrough rows
            self._dim_value_labels[key] = value_label
            # A stack so locking swaps the plain value for the spinbox in place,
            # keeping the row's height and position steady.
            stack = QStackedWidget()
            stack.addWidget(value_label)   # index 0: locked, a plain value
            stack.addWidget(box)           # index 1: unlocked, editable
            self._dim_stacks[key] = stack
            self._add_row(key, label_text, stack)
        self._dimensions_hint = QLabel("Sized from the input image. Unlock to override.")
        self._dimensions_hint.setObjectName("dimensionsHint")
        self._dimensions_hint.setWordWrap(True)
        self._sections["Dimensions"].content_form().addRow(self._dimensions_hint)
        # A free-floating padlock toggle, parented to the Dimensions content so it
        # folds with the section; placed by :meth:`_position_unlock_button`.
        content = self._sections["Dimensions"].content()
        btn = QToolButton(content)
        btn.setObjectName("dimensionUnlock")
        btn.setCheckable(True)
        btn.setText(_LOCK_CLOSED)
        btn.setToolTip("Unlock to override the size derived from the input image")
        # Pin a compact font so the padlock stays a small icon under the form's
        # larger heading font, keeping its width predictable for the gutter.
        lock_font = btn.font()
        lock_font.setPointSize(_UNLOCK_FONT_PT)
        btn.setFont(lock_font)
        btn.toggled.connect(self._on_dimensions_unlock_toggled)
        btn.adjustSize()
        self._unlock_btn = btn
        content.installEventFilter(self)  # follow the section's own relayouts
        # Recompute the shown size whenever the input image changes, and seed it now.
        image = self._widgets.get("input_image")
        if image is not None:
            image.textChanged.connect(self._update_derived_display)
        self._update_derived_display()

    def _position_unlock_button(self):
        """Center the unlock toggle vertically between the width and height rows,
        inside a left gutter reserved for it so it sits clear of the "Width"/
        "Height" labels. The gutter is the section's left margin, sized to the
        button here (the button's final width isn't known until its font and
        stylesheet apply, after construction). In the Dimensions content's
        coordinates (the toggle's parent). A no-op while the section is folded (the
        toggle hides with it) or on a manual-size form."""
        btn = self._unlock_btn
        if btn is None or self._sections["Dimensions"].is_collapsed():
            return
        btn.adjustSize()
        gutter = btn.width() + 10  # room for the button plus a small gap to the labels
        form = self._sections["Dimensions"].content_form()
        if form.contentsMargins().left() != gutter:
            # Push the labels over to open the gutter; the relayout re-invokes us
            # with the rows in their new positions.
            form.setContentsMargins(gutter, 2, 0, 4)
            return
        top = self._dim_stacks["width"].geometry()
        bottom = self._dim_stacks["height"].geometry()
        y = (top.center().y() + bottom.center().y()) // 2 - btn.height() // 2
        x = max(0, (gutter - btn.width()) // 2)
        btn.move(x, y)
        btn.raise_()

    def _dimensions_unlocked(self) -> bool:
        """True when the user has unlocked the derived size to override it."""
        return self._unlock_btn is not None and self._unlock_btn.isChecked()

    def _on_dimensions_unlock_toggled(self, unlocked: bool):
        """Flip the padlock and swap each dimension between its plain locked value
        and its editable spinbox, re-locking back onto the derived size. Announces
        the change so the panel refreshes with it."""
        self._unlock_btn.setText(_LOCK_OPEN if unlocked else _LOCK_CLOSED)
        self._unlock_btn.setToolTip(
            "Re-lock to the size derived from the input image" if unlocked
            else "Unlock to override the size derived from the input image"
        )
        for stack in self._dim_stacks.values():
            stack.setCurrentIndex(1 if unlocked else 0)
        if not unlocked:
            self._update_derived_display()
        self._position_unlock_button()  # the glyph swap can change the button's width
        self.changed.emit()

    def _update_derived_display(self):
        """Fill the locked width/height with the size the current input image
        derives — the plain value label and the spinbox behind it both, so
        unlocking starts from that value (0 → em dash when none can be measured).
        A no-op while unlocked, so it never clobbers a value the user is editing."""
        if self._size_deriver is None or self._dimensions_unlocked():
            return
        size = self._size_deriver(self.get_values_static())
        for key, value in zip(("width", "height"), size or (0, 0)):
            box = self._widgets[key]
            blocked = box.blockSignals(True)  # a display refresh isn't a user edit
            box.setValue(value)
            box.blockSignals(blocked)
            self._dim_value_labels[key].setText(str(value) if value else "—")

    def _override_dimensions(self) -> dict:
        """The explicit width/height to emit — only when the pair is unlocked and
        holds a real size. Locked (the default), the form emits nothing so the
        payload derives the size in the usual way."""
        if not self._dimensions_unlocked():
            return {}
        width = self._widgets["width"].value()
        height = self._widgets["height"].value()
        return {"width": width, "height": height} if width > 0 and height > 0 else {}

    def _apply_dimension_values(self, params: dict):
        """Reflect a loaded config's size in the derived pair: an explicit
        width/height (a saved override) unlocks and shows them; their absence
        re-locks the pair onto the derived size."""
        override = override_size(params)
        self._unlock_btn.setChecked(override is not None)
        if override is not None:
            self._widgets["width"].setValue(override[0])
            self._widgets["height"].setValue(override[1])
        else:
            self._update_derived_display()

    def _browse_image(self, key: str):
        """Pick an input image anywhere on disk via the native file dialog.

        The chosen path is stored verbatim: ComfyUI's ``LoadImage`` resolves a
        bare name against its input folder but takes an absolute path outside
        it unchanged, so a full path lets the user draw an input from anywhere.
        """
        pd = next((p for p in self._param_defs if p.key == key), None)
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Select Input Image",
            self._initial_browse_path(
                self._widgets[key].text().strip(), pd.browse_dir if pd else None
            ),
            "Images (*.png *.jpg *.jpeg *.webp);;All Files (*)",
        )
        if path:
            self._widgets[key].setText(path)

    @staticmethod
    def _initial_browse_path(current: str, home: Path | None = None) -> str:
        """Where the file dialog opens: the current value's own location when it
        points at a real file (a full path, or a bare name from ComfyUI's input
        folder), else the field's home folder — the one its ParamDef names, or
        ComfyUI's input folder for a field naming none. A named folder that isn't
        on this machine (a checkout without the library) falls back the same way,
        since a dialog pointed at a missing path opens wherever it likes."""
        if current:
            full = Path(current)
            if full.is_file():
                return str(full)
            in_input = COMFYUI_INPUT_DIR / current
            if in_input.is_file():
                return str(in_input)
        if home is not None and home.is_dir():
            return str(home)
        return str(COMFYUI_INPUT_DIR)

    def _wire_changed(self, widget: QWidget):
        """Re-emit ``changed`` whenever this input's value changes."""
        if isinstance(widget, (QPlainTextEdit, QLineEdit)):
            widget.textChanged.connect(self.changed)
        elif isinstance(widget, (QSpinBox, QDoubleSpinBox)):
            widget.valueChanged.connect(self.changed)
        elif isinstance(widget, QComboBox):
            widget.currentIndexChanged.connect(self.changed)
        elif isinstance(widget, CheckBox):
            widget.toggled.connect(self.changed)

    def _make_widget(self, pd: ParamDef) -> QWidget:
        if pd.type == "bool":
            # An on/off setting (the enhance toggle): a bare checkbox, its label
            # provided by the form row like every other field's.
            w = CheckBox("")
            w.setChecked(bool(pd.default))
            return w
        if pd.type == "str" and pd.multiline:
            w = QPlainTextEdit()
            w.setPlainText(str(pd.default))
            w.setMaximumHeight(100)
            return w
        if pd.type == "str":
            w = QLineEdit()
            w.setText(str(pd.default))
            return w
        if pd.type == "seed":
            w = QLineEdit()
            w.setText(str(pd.default))
            w.setPlaceholderText("64-bit integer seed")
            return w
        if pd.type == "int":
            w = NoWheelSpinBox()
            w.setMinimum(int(pd.min_val or 0))
            w.setMaximum(int(pd.max_val or 999999))
            w.setSingleStep(int(pd.step or 1))
            w.setValue(int(pd.default))
            return w
        if pd.type == "float":
            w = NoWheelDoubleSpinBox()
            w.setMinimum(pd.min_val or 0.0)
            w.setMaximum(pd.max_val or 999999.0)
            w.setSingleStep(pd.step or 0.1)
            w.setDecimals(2)
            w.setValue(float(pd.default))
            return w
        if pd.type == "combo":
            w = NoWheelComboBox()
            if pd.options:
                w.addItems(pd.options)
            _select_combo_value(w, str(pd.default))
            return w
        if pd.type == "image":
            w = QLineEdit()
            w.setText(str(pd.default))
            return w
        w = QLineEdit()
        w.setText(str(pd.default))
        return w

    def get_values(self) -> dict:
        """Read current values; a seed with its Random box checked is randomized."""
        return self._collect(randomize_seed=True)

    def get_values_static(self) -> dict:
        """Read current values without randomizing; a seed is read from its field.

        Used to snapshot a panel's settings for comparison, where a fresh random
        seed each call would make equality checks meaningless.
        """
        return self._collect(randomize_seed=False)

    def seed_is_random(self) -> bool:
        """True if any seed param's Random box is checked."""
        return any(cb.isChecked() for cb in self._randomize_checks.values())

    def set_seed_random(self, is_random: bool):
        """Set every seed's Random box, e.g. when restoring a saved tab.

        ``set_values`` always unchecks Random (it pins a concrete seed); this
        lets a caller put the box back the way the user had it.
        """
        for cb in self._randomize_checks.values():
            cb.setChecked(is_random)

    def _read_field(self, pd: ParamDef, randomize_seed: bool):
        """One field's current value. A seed with its Random box checked is
        re-rolled when ``randomize_seed``; otherwise it's read from the field."""
        w = self._widgets[pd.key]
        if pd.type == "bool":
            return w.isChecked()
        if pd.type == "seed":
            cb = self._randomize_checks.get(pd.key)
            if randomize_seed and cb and cb.isChecked():
                return random.randint(0, _SEED_MAX)
            try:
                return int(w.text())
            except ValueError:
                return 0
        if pd.type == "str" and pd.multiline:
            return w.toPlainText()
        if pd.type == "image":
            return _clean_image_ref(w.text())
        if pd.type == "str":
            return w.text()
        if pd.type in ("int", "float"):
            return w.value()
        if pd.type == "combo":
            return w.currentText()
        return None

    def _write_field(self, pd: ParamDef, value) -> None:
        """Apply one value to its widget. A seed is pinned (its Random box cleared),
        matching how reusing a generation reproduces an exact seed."""
        w = self._widgets[pd.key]
        if pd.type == "bool":
            w.setChecked(bool(value))
        elif pd.type == "seed":
            w.setText(str(int(value)))
            cb = self._randomize_checks.get(pd.key)
            if cb:
                cb.setChecked(False)
        elif pd.type == "str" and pd.multiline:
            w.setPlainText(str(value))
        elif pd.type == "str" or pd.type == "image":
            w.setText(str(value))
        elif pd.type == "int":
            w.setValue(int(value))
        elif pd.type == "float":
            w.setValue(float(value))
        elif pd.type == "combo":
            _select_combo_value(w, str(value))

    def _collect(self, randomize_seed: bool) -> dict:
        # Start from the params this form carries without showing — the extras it
        # has no field for, then the deliberately hidden ones (both disjoint from
        # the widget keys) — then lay the live field values on top, then any
        # unlocked size override, which is absent (so the payload derives the
        # size) unless the user set one.
        result = dict(self._passthrough)
        result.update(self._hidden)
        for pd in self._param_defs:
            result[pd.key] = self._read_field(pd, randomize_seed)
        result.update(self._override_dimensions())
        return result

    def set_values(self, params: dict):
        # Retain any params without a field so they survive the read-back, and show
        # them as read-only rows in the matching section; the rest are applied to
        # their widgets. A hidden key is dropped entirely — neither shown nor
        # absorbed — so the form keeps emitting the workflow's default for it.
        self._passthrough = {
            k: v for k, v in params.items()
            if k not in self._widgets and k not in self._hidden_keys
        }
        self._render_readonly_rows(self._passthrough)
        for pd in self._param_defs:
            if pd.key in params:
                self._write_field(pd, params[pd.key])
        # The derived width/height aren't declared params, so apply them here:
        # a saved override unlocks and shows, its absence re-locks onto the size
        # the just-applied input image derives.
        if self._size_deriver is not None:
            self._apply_dimension_values(params)

    def _render_readonly_rows(self, extras: dict):
        """Show each param the form has no field for as a read-only ``key: value``
        row, dropped into its section at its canonical position. Replaces any rows
        a prior ``set_values`` added, so switching generations never stacks them."""
        for title, key, value_label in self._readonly_rows:
            self._sections[title].content_form().removeRow(value_label)
            self._present_keys[title].remove(key)
        self._readonly_rows = []
        for key in sorted(extras, key=param_sections.key_rank):
            display = QLabel(str(extras[key]))
            display.setObjectName("readonlyParamValue")
            display.setWordWrap(True)
            display.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            # A row you cannot change is the one you most want explained, so a
            # passthrough gets the same tooltip an editable field would.
            display.setToolTip(param_help(key))
            self._add_row(key, key, display)
            self._readonly_rows.append((param_sections.section_title(key), key, display))
        self._refresh_section_visibility()

import random
from pathlib import Path

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPlainTextEdit, QLineEdit, QSpinBox, QDoubleSpinBox,
    QComboBox, QPushButton, QFileDialog,
)
from PyQt6.QtCore import Qt, QEvent, pyqtSignal

from origenerator.config import COMFYUI_INPUT_DIR
from origenerator.gui.collapsible_section import CollapsibleSection
from origenerator.gui.copy_button import CopyButton
from origenerator.gui.no_wheel import NoWheelComboBox, NoWheelDoubleSpinBox, NoWheelSpinBox
from origenerator.gui import param_sections
from origenerator.paths import ensure_shared_ui_on_path
from origenerator.reveal import show_in_explorer
from origenerator.workflows.base import ParamDef

ensure_shared_ui_on_path()
from shared_ui.check_box import CheckBox

_SEED_MAX = (1 << 63) - 1

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
    """

    changed = pyqtSignal()          # any field's value changed

    def __init__(self, param_defs: list[ParamDef], parent=None):
        super().__init__(parent)
        self._widgets: dict[str, QWidget] = {}
        self._randomize_checks: dict[str, CheckBox] = {}
        self._browse_buttons: dict[str, QPushButton] = {}
        # "Show in Explorer" buttons, one per image field, to reveal the chosen
        # file selected in Windows Explorer. Each stays disabled until its field
        # names a file that exists on disk.
        self._reveal_buttons: dict[str, QPushButton] = {}
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
        self._param_defs = param_defs
        self._build(param_defs)

    def _build(self, defs: list[ParamDef]):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(10)

        specs = [(s.title, s.collapsed) for s in param_sections.SECTIONS]
        specs.append((param_sections.OTHER_TITLE, param_sections.OTHER_COLLAPSED))
        for title, collapsed in specs:
            section = CollapsibleSection(title, collapsed=collapsed)
            section.toggled.connect(self._position_swap_button)
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
        self._refresh_section_visibility()

    def _add_row(self, key: str, label: str, field):
        """Insert one row (a field cell or a read-only value) into its section at
        the canonical position among the rows already there. ``field`` is a
        ``QWidget`` or a ``QLayout`` (a field paired with its trailing controls)."""
        title = param_sections.section_title(key)
        keys = self._present_keys[title]
        index = self._insert_index(keys, key)
        self._sections[title].content_form().insertRow(index, label, field)
        keys.insert(index, key)

    @staticmethod
    def _insert_index(present: list[str], key: str) -> int:
        """The row index ``key`` belongs at among ``present`` (kept in canonical
        order): the count of present keys that rank before it."""
        rank = param_sections.key_rank(key)
        return sum(1 for k in present if param_sections.key_rank(k) < rank)

    def _refresh_section_visibility(self):
        """Show a section iff it holds any row; empty ones take no space. Then
        re-place the swap button, since the sections above it may have moved."""
        for title, section in self._sections.items():
            section.setVisible(bool(self._present_keys[title]))
        self._position_swap_button()

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
            extras.append(self._make_reveal_button(pd.key))
        return extras

    def _make_reveal_button(self, key: str) -> QPushButton:
        """A "Show in Explorer" button for an image field: reveals the current
        file selected in Explorer, and greys out while the field names no file
        that exists (an empty path or a stale name)."""
        reveal = QPushButton("Show in Explorer")
        reveal.clicked.connect(
            lambda _checked=False, key=key: self._reveal_image(key)
        )
        self._reveal_buttons[key] = reveal
        # The field already holds its default; track edits so enablement stays live.
        self._widgets[key].textChanged.connect(
            lambda _text=None, key=key: self._sync_reveal_enabled(key)
        )
        self._sync_reveal_enabled(key)
        return reveal

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

        It floats to the left of the two labels, midway between their rows, so it
        reads as linking the pair rather than trailing either field. As a free
        child of the Dimensions section's content (not a form cell) it folds away
        with the section and needs manual placement — see
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
        """Center the swap button between the width and height rows, just left of
        their labels — in the Dimensions content's coordinates, its parent. Called
        on every resize/show/toggle since a free child gets no help from the
        layout; a no-op while the section is folded (the button hides with it)."""
        btn = self._swap_dimensions_btn
        if btn is None or self._sections["Dimensions"].is_collapsed():
            return
        btn.adjustSize()
        top = self._widgets["width"].geometry()
        bottom = self._widgets["height"].geometry()
        y = (top.center().y() + bottom.center().y()) // 2 - btn.height() // 2
        # Labels are right-aligned in a shared column, so the wider word starts
        # leftmost; sit a small gap to the left of it, clamped to the form edge.
        label = self._width_label.geometry()
        fm = self._width_label.fontMetrics()
        text_left = label.right() - max(
            fm.horizontalAdvance(self._width_label.text()),
            fm.horizontalAdvance(self._height_label.text()),
        )
        x = max(0, text_left - btn.width() - 6)
        btn.move(x, y)
        btn.raise_()

    def eventFilter(self, obj, event):
        # Installed on the Dimensions content: re-place the swap button whenever
        # that content relays out (unfolding, or the form growing wider).
        if event.type() in (QEvent.Type.Resize, QEvent.Type.Show):
            self._position_swap_button()
        return super().eventFilter(obj, event)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._position_swap_button()

    def showEvent(self, event):
        super().showEvent(event)
        self._position_swap_button()

    def swap_dimensions(self):
        """Exchange the width and height field values."""
        width, height = self._widgets["width"], self._widgets["height"]
        w, h = width.value(), height.value()
        width.setValue(h)
        height.setValue(w)

    def _browse_image(self, key: str):
        """Pick an input image anywhere on disk via the native file dialog.

        The chosen path is stored verbatim: ComfyUI's ``LoadImage`` resolves a
        bare name against its input folder but takes an absolute path outside
        it unchanged, so a full path lets the user draw an input from anywhere.
        """
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Select Input Image",
            self._initial_browse_path(self._widgets[key].text().strip()),
            "Images (*.png *.jpg *.jpeg *.webp);;All Files (*)",
        )
        if path:
            self._widgets[key].setText(path)

    def _reveal_image(self, key: str):
        """Show the field's file selected in Explorer. A no-op when the field
        names nothing on disk — the button is disabled then, but a stray call
        (e.g. a keyboard activation mid-edit) must not spawn a stray window."""
        resolved = self._resolve_existing_file(self._widgets[key].text())
        if resolved is not None:
            show_in_explorer(resolved)

    def _sync_reveal_enabled(self, key: str):
        """Enable Show-in-Explorer only while the field resolves to a real file;
        a greyed-out button with a hint beats one that opens the wrong place."""
        resolved = self._resolve_existing_file(self._widgets[key].text())
        btn = self._reveal_buttons[key]
        btn.setEnabled(resolved is not None)
        btn.setToolTip(
            f"Show {resolved} in Explorer" if resolved is not None
            else "Enter or browse to an image file first"
        )

    @staticmethod
    def _initial_browse_path(current: str) -> str:
        """Where the file dialog opens: the current value's own location when it
        points at a real file (a full path, or a bare name from ComfyUI's input
        folder), else the input folder as a sensible home."""
        resolved = ParamForm._resolve_existing_file(current)
        return str(resolved) if resolved is not None else str(COMFYUI_INPUT_DIR)

    @staticmethod
    def _resolve_existing_file(current: str) -> Path | None:
        """The existing file a ``LoadImage`` value points at, or ``None``.

        Resolves the way ComfyUI does: a full path taken as-is, else a bare name
        against ComfyUI's input folder. ``None`` when the field is empty or names
        nothing on disk — used both to open Browse in the right place and to
        gate the Show-in-Explorer button."""
        current = _clean_image_ref(current)
        if not current:
            return None
        full = Path(current)
        if full.is_file():
            return full
        in_input = COMFYUI_INPUT_DIR / current
        if in_input.is_file():
            return in_input
        return None

    def _wire_changed(self, widget: QWidget):
        """Re-emit ``changed`` whenever this input's value changes."""
        if isinstance(widget, (QPlainTextEdit, QLineEdit)):
            widget.textChanged.connect(self.changed)
        elif isinstance(widget, (QSpinBox, QDoubleSpinBox)):
            widget.valueChanged.connect(self.changed)
        elif isinstance(widget, QComboBox):
            widget.currentIndexChanged.connect(self.changed)

    def _make_widget(self, pd: ParamDef) -> QWidget:
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
        if pd.type == "seed":
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
        # Start from the hidden params (disjoint from the widget keys), then lay
        # the live field values on top.
        result = dict(self._passthrough)
        for pd in self._param_defs:
            result[pd.key] = self._read_field(pd, randomize_seed)
        return result

    def set_values(self, params: dict):
        # Retain any params without a field so they survive the read-back, and show
        # them as read-only rows in the matching section; the rest are applied to
        # their widgets.
        self._passthrough = {k: v for k, v in params.items() if k not in self._widgets}
        self._render_readonly_rows(self._passthrough)
        for pd in self._param_defs:
            if pd.key in params:
                self._write_field(pd, params[pd.key])

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
            self._add_row(key, key, display)
            self._readonly_rows.append((param_sections.section_title(key), key, display))
        self._refresh_section_visibility()

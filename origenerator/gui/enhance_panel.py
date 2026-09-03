"""The app's enhancement settings, at the bottom of the browser pane.

Enhancement is not one of the settings that decide which folder a generation
lands in — it is a finish applied to an image afterward — so it is deliberately
not on the Generate form beside Seed, Dimensions and Output. It lives here
instead, beside Genau's console, and it is app-wide: whatever is set here is
what Enhance All runs with, what a single image's Enhance action runs with, and
— with the box ticked — what every image the app newly generates receives as it
lands. It follows you rather than the folder, so it shows on the shelves
(Recents, Starred, Experiments) exactly as it does on a settings folder.

Editing writes straight back through ``on_change`` — there is no Apply button —
and the settings persist with the rest of the session state. Auto-enhance is a
bare switch on the title row rather than a labeled checkbox among the knobs: it
is the panel's power, not one of its dials.

An enhancement level dragged in from the info pane's version strip is absorbed:
the settings that made that version become the ones on the panel, so "do that
again" doesn't mean reading its numbers off and typing them back in.

Each part the detail pass can redraw is a box to tick and a denoise to run it
at: the tick is whether that part is fixed at all, so an unticked part greys its
own name and number rather than making zero mean off. A part whose detector
isn't installed in ComfyUI can't be ticked at all, and says why — the
alternative being a run that fails on submit.
"""

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QFormLayout, QGridLayout, QHBoxLayout, QLabel, QVBoxLayout, QWidget,
)

from origenerator.gallery import (
    ENHANCE_SETTING_KEYS, ENHANCE_WORKFLOW, MATCH_SOURCE_MODEL, EnhanceSettings,
)
from origenerator.gui.enhance_versions import params_from_mime
from origenerator.gui.flow_layout import FlowLayout
from origenerator.gui.param_help import param_help
from origenerator.gui.no_wheel import (
    NoWheelComboBox, NoWheelDoubleSpinBox, NoWheelSpinBox,
)
from origenerator.gui.toggle_switch import ToggleSwitch
from origenerator.paths import ensure_shared_ui_on_path
from origenerator.workflows import WORKFLOW_REGISTRY
from origenerator.workflows.detail_parts import (
    DEFAULT_FIX_DENOISE, DETAIL_PARTS, detail_fixes_of, detector_for_part,
)
# Before any shared_ui import: that checkout is a sibling on the path, not a
# dependency the launch interpreter has installed (see tests/test_sibling_imports).
ensure_shared_ui_on_path()

from shared_ui.check_box import CheckBox
from shared_ui.colors import BG_PRIMARY, BORDER_SUBTLE, TEXT_MUTED

_AUTO_TOOLTIP = (
    "Enhance every image generated from now on, as it lands — with the settings "
    "below. The original is kept, so an enhancement can always be compared "
    "against it or redone."
)
_NO_DETECTOR_TOOLTIP = (
    "Unavailable: ComfyUI hasn't got a model that finds {}. Install the Impact "
    "Subpack node pack, put one whose name says \"{}\" in its "
    "models/ultralytics/bbox folder, and restart it."
)
# What a fix field costs around its digits: the padding either side below, its
# 1px border, and the pixels a spin box keeps for its cursor and its own inner
# margin. Measured by rendering one and looking, since a field a hair too narrow
# doesn't complain — it clips a digit off 0.45, which still reads as a number.
_FIX_FIELD_PADDING = 4
_FIX_FIELD_CHROME = _FIX_FIELD_PADDING * 2 + 2 + 16
# Disabling a widget is not the same as it looking disabled: the app's sheet
# colors every label, picker and spin box outright and names no disabled state,
# so a panel switched off went on reading exactly as live as before. These mute
# this panel's own fields — set on the panel, so nothing outside it is touched.
# (The auto switch is the exception: it paints itself, and dims itself.)
_FIX_FIELD_CSS = f"""
    #enhancePanel QDoubleSpinBox#fixField {{
        /* The app sheet holds 18px on the right of every spin box for the step
           buttons. These have none, and seven fields' worth of held-back space
           is the difference between one line of parts and two. */
        padding: {_FIX_FIELD_PADDING}px;
    }}
"""
_DISABLED_CSS = f"""
    #enhancePanel QLabel:disabled,
    #enhancePanel QComboBox:disabled,
    #enhancePanel QSpinBox:disabled,
    #enhancePanel QDoubleSpinBox:disabled {{
        color: {TEXT_MUTED.name()};
    }}
    #enhancePanel QComboBox:disabled,
    #enhancePanel QSpinBox:disabled,
    #enhancePanel QDoubleSpinBox:disabled {{
        background-color: {BG_PRIMARY.name()};
        border: 1px solid {BORDER_SUBTLE.name()};
    }}
"""


def _read(widget):
    """What one field reads as, in the type its param is stored as."""
    if isinstance(widget, NoWheelComboBox):
        return widget.currentText()
    return widget.value()


def _fill(widget, value) -> None:
    """Put a stored value into one field, coercing what JSON handed back.

    A picker offered a name it no longer has an option for keeps it anyway: a
    folder configured against a since-removed model must come back reading as
    that model rather than silently snapping to whatever sorts first.
    """
    if isinstance(widget, NoWheelComboBox):
        index = widget.findText(str(value))
        if index < 0:
            widget.addItem(str(value))
            index = widget.findText(str(value))
        widget.setCurrentIndex(index)
    elif isinstance(widget, NoWheelSpinBox):
        widget.setValue(int(value))
    else:
        widget.setValue(float(value))


def _enhancer_param_defs() -> dict:
    """The standalone enhancer's own knob definitions, keyed by param — so this
    panel's ranges, steps and option lists can't drift from the workflow's.

    Read once per panel: ``param_definitions`` scans the model directories, and
    every field here would otherwise pay for that scan again.
    """
    return {
        pd.key: pd
        for pd in WORKFLOW_REGISTRY[ENHANCE_WORKFLOW].param_definitions()
    }


class EnhancePanel(QWidget):
    """The Enhance subpanel: an auto box over the knobs an enhancement runs at.

    ``show_settings`` loads a stored configuration (or the defaults, before
    anything has been set); every edit calls back with the new
    :class:`~origenerator.gallery.enhance.EnhanceSettings`. The panel holds no
    state of its own beyond its fields — the gallery keeps the value and routes
    it where it's needed — so it stays a plain editor.
    """

    def __init__(self, on_change, parent=None):
        super().__init__(parent)
        self._on_change = on_change
        self._loading = False  # suppress the write-back while filling the fields
        self._widgets: dict = {}
        self._defs = _enhancer_param_defs()
        self.setAcceptDrops(True)  # a version tile dropped here hands its settings over
        self.setObjectName("enhancePanel")
        self.setStyleSheet(_DISABLED_CSS + _FIX_FIELD_CSS)

        box = QVBoxLayout(self)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(4)
        # The title row, with the auto switch at its far right — a bare switch,
        # the way a panel's power is a switch on its corner rather than a line
        # of prose among its dials. What it does is in its tooltip; the knobs
        # below are what it does it with.
        title_row = QHBoxLayout()
        title_row.setContentsMargins(0, 0, 0, 0)
        heading = QLabel("Enhance")
        heading.setStyleSheet("font-weight: 600;")
        title_row.addWidget(heading)
        title_row.addStretch(1)
        self._auto = ToggleSwitch()
        self._auto.setToolTip(_AUTO_TOOLTIP)
        self._auto.toggled.connect(self._emit)
        title_row.addWidget(self._auto)
        box.addLayout(title_row)

        form = QFormLayout()
        form.setContentsMargins(0, 0, 0, 0)
        form.setSpacing(4)
        self._model = NoWheelComboBox()
        # The default leaves the refining model to whatever made the image, which
        # is what keeps an enhanced image in its own style; picking a checkpoint
        # here overrides that for every enhance this folder runs.
        self._model.addItem(MATCH_SOURCE_MODEL)
        self._model.addItems(self._options("checkpoint"))
        self._model.currentIndexChanged.connect(self._emit)
        self._model.setToolTip(
            "Which model does the refining. Left at "
            f"\"{MATCH_SOURCE_MODEL}\" each image is enhanced by whatever made "
            "it, so it stays in its own style; pick one to pin it instead."
        )
        self._widgets["checkpoint"] = self._model
        form.addRow(self._labeled("Model:", self._model), self._model)

        self._upscaler = NoWheelComboBox()
        self._upscaler.addItems(self._options("upscale_model"))
        self._upscaler.currentIndexChanged.connect(self._emit)
        self._upscaler.setToolTip(param_help("upscale_model"))
        self._widgets["upscale_model"] = self._upscaler
        form.addRow(self._labeled("Upscaler:", self._upscaler), self._upscaler)

        # The three numbers on one line: they are read together (how much bigger,
        # how long, how far from the source) and the pane is not wide.
        numbers = QHBoxLayout()
        numbers.setContentsMargins(0, 0, 0, 0)
        numbers.setSpacing(4)
        self._scale = self._number("enhance_scale", NoWheelDoubleSpinBox())
        self._steps = self._number("enhance_steps", NoWheelSpinBox())
        self._denoise = self._number("enhance_denoise", NoWheelDoubleSpinBox())
        for label, widget in (("Scale", self._scale), ("Steps", self._steps),
                              ("Denoise", self._denoise)):
            numbers.addWidget(self._labeled(label, widget))
            numbers.addWidget(widget, 1)
        form.addRow(numbers)

        # The detail pass: a box and a number per part it can be aimed at, the
        # number being the denoise that part is redrawn at. Their denoise is
        # separate from the one above, and from each other's, because it can
        # afford to be far bolder: nothing outside the regions a detector finds
        # is touched, and a mouth wants a harder redraw than a face does.
        fix_heading = QLabel("Fixes")
        fix_heading.setToolTip(param_help("enhance_detail_fixes"))
        form.addRow(fix_heading)
        form.addRow(self._fix_row())

        box.addLayout(form)
        box.addStretch(1)

    def _fix_row(self) -> QWidget:
        """Every fixable part on one line: a box to tick over its name and the
        denoise it runs at.

        The tick is what turns a part's fix on, so the number underneath is free
        to sit at the denoise it would run at whether or not it is running —
        tick a part and it fixes at that, untick it and the number is still
        there for next time, greyed along with the name so the line reads at a
        glance as which parts are on.

        Each number is exactly as wide as its digits need — no floor, no share
        of the leftover — because the point of the line is reading all the parts
        at once, and one number stretched to fill a pane costs another part its
        place. (The three numbers above take the opposite deal, a floor each and
        the slack between them: there are only three, and they are the
        enhancement itself rather than a list.)

        Flowed rather than fixed, so a pane too narrow for the line wraps the
        last parts onto a second one instead of cutting them off — and so the
        line never widens the window, which tiles into a third of a monitor.
        Each part's box, name and number travel together, so a wrap can't
        separate them.

        Every part the app knows is here, installed detector or not: one with
        nothing to find it can't be ticked, and says which file to add — which
        tells you more than an absent field (nothing at all to notice) and far
        more than a live one that would be rejected on submit.
        """
        host = QWidget()
        flow = FlowLayout(host, spacing=4)
        # Without this the form gives the line one row's worth of height however
        # many it wraps to, and the parts past the first row are simply cut off:
        # a widget only offers its layout's height-for-width when its policy
        # says it has one.
        policy = host.sizePolicy()
        policy.setHeightForWidth(True)
        host.setSizePolicy(policy)
        self._fixes = {}
        self._fix_checks = {}
        for part in DETAIL_PARTS:
            flow.addWidget(self._fix_field(part))
        return host

    def _fix_field(self, part) -> QWidget:
        """One part's column: its tick box, over its name and its denoise."""
        check = CheckBox("")
        check.setToolTip(param_help("enhance_detail_fixes"))
        widget = self._fix_number()
        label = self._labeled(part.name.capitalize(), widget)
        if detector_for_part(part) is None:
            reason = _NO_DETECTOR_TOOLTIP.format(part.name, part.matches[0])
            check.setEnabled(False)
            for one in (check, widget, label):
                one.setToolTip(reason)
        check.toggled.connect(lambda _on, name=part.name: self._fix_toggled(name))

        column = QWidget()
        grid = QGridLayout(column)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(2)
        grid.addWidget(check, 0, 1, Qt.AlignmentFlag.AlignCenter)
        grid.addWidget(label, 1, 0)
        grid.addWidget(widget, 1, 1)

        self._fixes[part.name] = widget
        self._fix_checks[part.name] = check
        self._show_fix_on(part.name)
        return column

    def _fix_toggled(self, name: str) -> None:
        """A part switched on or off: grey its name and number to match, and
        report the settings the panel now reads as."""
        self._show_fix_on(name)
        self._emit()

    def _show_fix_on(self, name: str) -> None:
        """Grey one part's name and number unless its box is ticked."""
        check = self._fix_checks[name]
        widget = self._fixes[name]
        on = check.isChecked() and check.isEnabled()
        widget.setEnabled(on)
        label = self._label_for(widget)
        if label is not None:
            label.setEnabled(on)

    def _fix_number(self) -> NoWheelDoubleSpinBox:
        """One part's denoise box, ranged from the enhancer's own ParamDef so a
        floor of zero — the value that means "leave this part alone" — stays the
        workflow's answer rather than this panel's.

        Sized to the digits it shows: Qt's own hint for a spin box is two and a
        half times ``0.00``, and seven of those hints is the difference between
        one line of parts and three. Measured off the font rather than typed as
        a number, so it still fits at another font size.
        """
        widget = NoWheelDoubleSpinBox()
        pd = self._defs.get("enhance_detail_fixes")
        widget.setMinimum(pd.min_val if pd is not None else 0.0)
        widget.setMaximum(pd.max_val if pd is not None else 1.0)
        widget.setSingleStep(pd.step if pd is not None and pd.step else 0.05)
        widget.setDecimals(2)
        # The denoise a fix runs at unless it is given another: the box beside
        # it is what says whether this part is fixed, so the number never has to
        # mean off, and a part ticked on runs at something sensible untouched.
        widget.setValue(DEFAULT_FIX_DENOISE)
        # No steppers: seven pairs of arrows cost more width than the numbers
        # beside them, and a denoise is typed or nudged with the arrow keys.
        widget.setButtonSymbols(NoWheelDoubleSpinBox.ButtonSymbols.NoButtons)
        widget.setObjectName("fixField")
        widget.setFixedWidth(widget.fontMetrics().horizontalAdvance("0.00")
                             + _FIX_FIELD_CHROME)
        widget.setToolTip(param_help("enhance_detail_fixes"))
        widget.valueChanged.connect(self._emit)
        return widget

    def set_applicable(self, applicable: bool, reason: str = "") -> None:
        """Switch the whole panel on or off, and look it.

        Off, every field is disabled *and* muted, so the panel reads as what it
        is where it can't apply — settings for an action that isn't on offer —
        rather than as live knobs that quietly do nothing. Back on, each field
        returns to whatever it was in its own right: a part stays grayed if
        ComfyUI still hasn't got a detector that finds it.
        """
        self.setEnabled(applicable)
        self.setToolTip("" if applicable else reason)

    def _label_for(self, widget) -> QLabel | None:
        """The caption sitting beside one field, or ``None`` before it has one.

        Read off the layout rather than kept in a dict of its own: the caption
        is put there by :meth:`_labeled`, and two records of the same pairing
        are one more thing to keep in step.
        """
        parent = widget.parentWidget()
        layout = parent.layout() if parent is not None else None
        if layout is None:
            return None
        for index in range(layout.count()):
            item = layout.itemAt(index).widget()
            if isinstance(item, QLabel):
                return item
        return None

    @staticmethod
    def _labeled(text: str, widget) -> QLabel:
        """A field's caption, carrying the field's own tooltip — the word is what
        you are looking at when you wonder what a setting does."""
        label = QLabel(text)
        label.setToolTip(widget.toolTip())
        return label

    def _options(self, key: str) -> list:
        """The installed files a picker offers, from the enhancer's own ParamDef."""
        pd = self._defs.get(key)
        return list(pd.options or []) if pd is not None else []

    def _number(self, key: str, widget):
        """One numeric knob, ranged from the enhancer's own ParamDef."""
        pd = self._defs.get(key)
        if pd is not None:
            widget.setMinimum(pd.min_val if pd.min_val is not None else 0)
            widget.setMaximum(pd.max_val if pd.max_val is not None else 999999)
            if pd.step:
                widget.setSingleStep(pd.step)
            if isinstance(widget, NoWheelDoubleSpinBox):
                widget.setDecimals(2)
            widget.setValue(pd.default)
        widget.setToolTip(param_help(key))
        # Three to a line in a pane that can tile narrow: a floor each, so they
        # stay readable rather than squeezing down to their arrows.
        widget.setMinimumWidth(70)
        widget.valueChanged.connect(self._emit)
        self._widgets[key] = widget
        return widget

    def show_settings(self, settings: EnhanceSettings) -> None:
        """Fill the panel from one folder's stored settings, writing nothing back.

        A part the settings don't name is a part left alone, so it reads zero —
        filling only what is named would leave the last folder's fixes standing
        on a folder that asked for none.
        """
        self._loading = True
        try:
            self._auto.setChecked(settings.auto)
            for key, widget in self._widgets.items():
                value = settings.params.get(key)
                if value is not None:
                    _fill(widget, value)
            fixes = detail_fixes_of(settings.params)
            for name, widget in self._fixes.items():
                # A part these settings don't name is off, its number left at
                # what a fix runs at rather than at some remembered value from
                # the folder before this one.
                widget.setValue(float(fixes.get(name, DEFAULT_FIX_DENOISE)))
                self._fix_checks[name].setChecked(name in fixes)
                self._show_fix_on(name)
        finally:
            self._loading = False

    def settings(self) -> EnhanceSettings:
        """What the panel currently reads as."""
        params = {}
        for key in ENHANCE_SETTING_KEYS:
            widget = self._widgets.get(key)
            if widget is not None:
                params[key] = _read(widget)
        # Only the parts ticked on: an unticked part is one this enhancement
        # doesn't touch, and carrying its number anyway would make two settings
        # that fix the same parts compare as different.
        params["enhance_detail_fixes"] = {
            name: widget.value() for name, widget in self._fixes.items()
            if self._fix_checks[name].isChecked()
        }
        return EnhanceSettings(auto=self._auto.isChecked(), params=params)

    def _emit(self, *_args):
        if not self._loading:
            self._on_change(self.settings())

    # --- absorbing a dragged enhancement level -----------------------------

    def dragEnterEvent(self, event):
        if params_from_mime(event.mimeData()) is not None:
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event):
        self.dragEnterEvent(event)

    def dropEvent(self, event):
        """Take the settings of the version dropped on us.

        The auto box is left as it is: the drop says what to enhance *at*, not
        whether to keep enhancing.
        """
        params = params_from_mime(event.mimeData())
        if params is None:
            event.ignore()
            return
        merged = dict(self.settings().params)
        merged.update({k: v for k, v in params.items() if k in ENHANCE_SETTING_KEYS})
        self.show_settings(EnhanceSettings(auto=self._auto.isChecked(), params=merged))
        self._emit()
        event.acceptProposedAction()

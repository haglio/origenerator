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

One knob here can be unavailable rather than merely unset: the detail pass needs
a face/hand detector installed in ComfyUI, so with none it is greyed with the
reason on it — the alternative being a tick that fails on submit.
"""

from PyQt6.QtWidgets import (
    QFormLayout, QHBoxLayout, QLabel, QVBoxLayout, QWidget,
)

from origenerator.gallery import (
    ENHANCE_SETTING_KEYS, ENHANCE_WORKFLOW, MATCH_SOURCE_MODEL, EnhanceSettings,
)
from origenerator.gui.enhance_versions import params_from_mime
from origenerator.gui.param_help import param_help
from origenerator.gui.no_wheel import (
    NoWheelComboBox, NoWheelDoubleSpinBox, NoWheelSpinBox,
)
from origenerator.gui.toggle_switch import ToggleSwitch
from origenerator.workflows import WORKFLOW_REGISTRY
from shared_ui.check_box import CheckBox
from shared_ui.colors import BG_PRIMARY, BORDER_SUBTLE, TEXT_MUTED

_AUTO_TOOLTIP = (
    "Enhance every image generated from now on, as it lands — with the settings "
    "below. The original is kept, so an enhancement can always be compared "
    "against it or redone."
)
_NO_DETECTOR_TOOLTIP = (
    "Unavailable: ComfyUI hasn't got what this needs. Install the Impact "
    "Subpack node pack, put {} and {} in its models/ultralytics/bbox folder, "
    "and restart it."
)
# Disabling a widget is not the same as it looking disabled: the app's sheet
# colors every label, picker and spin box outright and names no disabled state,
# so a panel switched off went on reading exactly as live as before. These mute
# this panel's own fields — set on the panel, so nothing outside it is touched.
# (The switch paints itself and dims itself; the check boxes already did.)
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
    if isinstance(widget, CheckBox):
        return widget.isChecked()
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
    elif isinstance(widget, CheckBox):
        widget.setChecked(bool(value))
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
        self.setStyleSheet(_DISABLED_CSS)

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

        # The detail pass and the denoise it runs at, on one line, reading as
        # the sentence it is: fix faces & hands at 0.45. Its denoise is separate
        # from the one above because it can afford to be far bolder — nothing
        # outside the regions it finds is touched.
        detail = QHBoxLayout()
        detail.setContentsMargins(0, 0, 0, 0)
        detail.setSpacing(4)
        self._detail = CheckBox("Fix faces & hands")
        self._detail.setToolTip(param_help("enhance_detail_fix"))
        self._detail.toggled.connect(self._emit)
        self._widgets["enhance_detail_fix"] = self._detail
        self._detail_denoise = self._number("enhance_detail_denoise",
                                            NoWheelDoubleSpinBox())
        detail.addWidget(self._detail)
        detail.addStretch(1)
        detail.addWidget(self._labeled("at", self._detail_denoise))
        detail.addWidget(self._detail_denoise)
        form.addRow(detail)
        self._show_detectors_installed()

        box.addLayout(form)
        box.addStretch(1)

    def set_applicable(self, applicable: bool, reason: str = "") -> None:
        """Switch the whole panel on or off, and look it.

        Off, every field is disabled *and* muted, so the panel reads as what it
        is where it can't apply — settings for an action that isn't on offer —
        rather than as live knobs that quietly do nothing. Back on, each field
        returns to whatever it was in its own right: the detail pass stays
        grayed if ComfyUI still hasn't got a detector.
        """
        self.setEnabled(applicable)
        self.setToolTip("" if applicable else reason)

    def _show_detectors_installed(self) -> None:
        """Dim the detail pass when ComfyUI hasn't got a detector it runs.

        The pass is the only setting here that can be unavailable rather than
        merely unset: the models that find the faces and hands are a separate
        install. It looks for two by name, so what matters is whether one of
        THOSE is there — some other detector in that folder would leave the box
        tickable and the pass finding nothing, which says less than a greyed box
        naming the file to add.
        """
        keys = ("enhance_face_detector", "enhance_hand_detector")
        found = [k for k in keys if self._defs[k].default in self._options(k)]
        for widget in (self._detail, self._detail_denoise):
            widget.setEnabled(bool(found))
            if not found:
                widget.setToolTip(_NO_DETECTOR_TOOLTIP.format(
                    *(self._defs[k].default for k in keys)))

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
        """Fill the panel from one folder's stored settings, writing nothing back."""
        self._loading = True
        try:
            self._auto.setChecked(settings.auto)
            for key, widget in self._widgets.items():
                value = settings.params.get(key)
                if value is not None:
                    _fill(widget, value)
        finally:
            self._loading = False

    def settings(self) -> EnhanceSettings:
        """What the panel currently reads as."""
        params = {}
        for key in ENHANCE_SETTING_KEYS:
            widget = self._widgets.get(key)
            if widget is not None:
                params[key] = _read(widget)
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

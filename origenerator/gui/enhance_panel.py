"""The open folder's enhancement settings, at the bottom of the browser pane.

Enhancement is not one of the settings that decide which folder a generation
lands in — it is a finish applied to an image afterward — so it is deliberately
not on the Generate form beside Seed, Dimensions and Output. It lives here
instead, beside Genau's console, and belongs to the FOLDER on screen: whatever
is set here is what Enhance All runs with, what a single image's Enhance action
runs with, and — with the box ticked — what every image the folder newly
generates receives as it lands.

Editing writes straight back through ``on_change``, the way the gallery's other
per-folder state persists: there is no Apply button, and the settings are read
again from the database each time the folder is opened.
"""

from PyQt6.QtWidgets import (
    QFormLayout, QHBoxLayout, QLabel, QVBoxLayout, QWidget,
)

from origenerator.gallery import (
    ENHANCE_SETTING_KEYS, ENHANCE_WORKFLOW, MATCH_SOURCE_MODEL, EnhanceSettings,
)
from origenerator.gui.no_wheel import (
    NoWheelComboBox, NoWheelDoubleSpinBox, NoWheelSpinBox,
)
from origenerator.paths import ensure_shared_ui_on_path
from origenerator.workflows import WORKFLOW_REGISTRY

ensure_shared_ui_on_path()
from shared_ui.check_box import CheckBox  # noqa: E402

_AUTO_TOOLTIP = (
    "Enhance every image this folder generates from now on, as it lands — with "
    "the settings below. The original is kept, so an enhancement can always be "
    "compared against it or redone."
)


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

    ``show_settings`` loads a folder's stored configuration (or the defaults for
    one never configured); every edit calls back with the new
    :class:`~origenerator.gallery.enhance.EnhanceSettings`. The panel carries no
    folder key of its own — the gallery knows which folder is open and routes the
    write — so it stays a plain editor of one value.
    """

    def __init__(self, on_change, parent=None):
        super().__init__(parent)
        self._on_change = on_change
        self._loading = False  # suppress the write-back while filling the fields
        self._widgets: dict = {}
        self._defs = _enhancer_param_defs()

        box = QVBoxLayout(self)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(4)
        heading = QLabel("Enhance")
        heading.setStyleSheet("font-weight: 600;")
        box.addWidget(heading)

        self._auto = CheckBox("Auto-enhance new images in this folder")
        self._auto.setToolTip(_AUTO_TOOLTIP)
        self._auto.toggled.connect(self._emit)
        box.addWidget(self._auto)

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
        self._widgets["checkpoint"] = self._model
        form.addRow("Model:", self._model)

        self._upscaler = NoWheelComboBox()
        self._upscaler.addItems(self._options("upscale_model"))
        self._upscaler.currentIndexChanged.connect(self._emit)
        self._widgets["upscale_model"] = self._upscaler
        form.addRow("Upscaler:", self._upscaler)

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
            numbers.addWidget(QLabel(label))
            numbers.addWidget(widget, 1)
        form.addRow(numbers)
        box.addLayout(form)
        box.addStretch(1)

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
        # Three to a line in a pane that can tile narrow: a floor each, so they
        # stay readable rather than squeezing down to their arrows.
        widget.setMinimumWidth(52)
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
                if value is None:
                    continue
                if widget is self._model or widget is self._upscaler:
                    index = widget.findText(str(value))
                    if index < 0:
                        widget.addItem(str(value))  # a model no longer installed
                        index = widget.findText(str(value))
                    widget.setCurrentIndex(index)
                elif isinstance(widget, NoWheelSpinBox):
                    widget.setValue(int(value))
                else:
                    widget.setValue(float(value))
        finally:
            self._loading = False

    def settings(self) -> EnhanceSettings:
        """What the panel currently reads as."""
        params = {}
        for key in ENHANCE_SETTING_KEYS:
            widget = self._widgets.get(key)
            if widget is None:
                continue
            params[key] = (
                widget.currentText() if isinstance(widget, NoWheelComboBox)
                else widget.value()
            )
        return EnhanceSettings(auto=self._auto.isChecked(), params=params)

    def _emit(self, *_args):
        if not self._loading:
            self._on_change(self.settings())

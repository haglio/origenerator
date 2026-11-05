from __future__ import annotations

from PyQt6.QtCore import QEvent, QPoint, QRect, QSignalBlocker, QSize, Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QPushButton,
    QScrollArea,
    QToolButton,
    QVBoxLayout,
    QWidget,
)
from shared_ui import palette
from shared_ui.chrome import control_ground
from shared_ui.colors import (
    BG_PRIMARY,
    BG_SECONDARY,
    BORDER_SUBTLE,
    TEXT_MUTED,
    YELLOW,
)
from shared_ui.icon_button import fill_square_with_icon
from shared_ui.icons import qt_icon
from shared_ui.spacing import BUTTON_SIZE_HUD, GAP_SMALL
from shared_ui.tick_control import TickControl
from shared_ui.toggle_switch import ToggleSwitch

from origenerator import enhance_presets, fix_training
from origenerator.enhance_presets import Preset
from origenerator.gallery import (
    ENHANCE_SETTING_KEYS,
    ENHANCE_WORKFLOW,
    MATCH_SOURCE_MODEL,
    EnhanceSettings,
    full_settings,
    models_matching_a_folders_sources,
    models_matching_the_sources,
)
from origenerator.gui.drop_target import DropTarget
from origenerator.gui.eliding import open_the_list_in_full
from origenerator.gui.enhance_versions import params_from_mime
from origenerator.gui.fix_prompts_parts import (
    foot_row,
    lora_dropdown,
    ok_and_cancel,
    prompt_boxes,
    prompts_side_by_side,
    strength_box,
    window_column,
)
from origenerator.gui.flow_layout import FieldGrid, FlowLayout
from origenerator.gui.lora_offers import trashed
from origenerator.gui.no_wheel import (
    NoWheelDoubleSpinBox,
    NoWheelDropdown,
    NoWheelSpinBox,
)
from origenerator.gui.panes import border_as_a_set
from origenerator.gui.param_fields import choose_option, offer_options
from origenerator.gui.param_help import definition_help, param_help, with_training_date
from origenerator.gui.training_controls import TrainingControls
from origenerator.gui.warning_mark import WarningMark
from origenerator.setting_advice import (
    fix_lora_model_warning,
    lost_lora_advice,
    trigger_word_advice,
)
from origenerator.workflows import WORKFLOW_REGISTRY
from origenerator.workflows.detail_parts import (
    DEFAULT_FIX_DENOISE,
    detail_fixes_of,
    detector_folder,
    detector_for_part,
    fix_prompts,
    fix_prompts_of,
    part_named,
    part_table,
)
from origenerator.workflows.image_enhance import ENHANCE_MODEL_FAMILIES
from origenerator.workflows.model_files import NO_LORA, list_lora_files

_NOT_READ = object()
_AUTO_TOOLTIP = (
    "Enhance every image generated from now on, as it lands — with the settings "
    "below. The original is kept, so an enhancement can always be compared "
    "against it or redone."
)

_ALL_FIXES_TOOLTIP = (
    "The tick turns every fix on or off together. A number typed here sets every "
    "fix to it, including the ones that are off. The number is empty while the "
    "fixes differ."
)

_NO_DETECTOR_TOOLTIP = (
    "Unavailable: ComfyUI hasn't got a model that finds {}. Install the Impact "
    "Subpack node pack, put one whose name says \"{}\" in its "
    "{} folder, and restart it."
)
_FIX_FIELD_PADDING = GAP_SMALL
_FIX_FIELD_CHROME = _FIX_FIELD_PADDING * 2 + 2 + 16
_NUMBER_FIELD_CHROME = 50
_FIX_FIELD_CSS = f"""
    #enhancePane QDoubleSpinBox#fixField {{
        /* The app sheet holds 18px on the right of every spinner for the step
           buttons. These have none, and seven fields' worth of held-back space
           is the difference between one line of parts and two. */
        padding: {_FIX_FIELD_PADDING}px;
    }}
"""
_DISABLED_CSS = f"""
    #enhancePane QLabel:disabled,
    #enhancePane QComboBox:disabled,
    #enhancePane QSpinBox:disabled,
    #enhancePane QDoubleSpinBox:disabled {{
        color: {TEXT_MUTED.name()};
    }}
    #enhancePane QComboBox:disabled,
    #enhancePane QSpinBox:disabled,
    #enhancePane QDoubleSpinBox:disabled {{
        background-color: {BG_PRIMARY.name()};
        border: 1px solid {BORDER_SUBTLE.name()};
    }}
"""


_ENHANCE_BUTTON_CSS = f"""
    #enhancePane QPushButton#enhanceButton {{
        color: {BG_PRIMARY.name()};
        border: 1px solid {YELLOW.name()};
        font-weight: bold;
    }}{control_ground(palette.YELLOW, "#enhancePane QPushButton#enhanceButton")}
    #enhancePane QPushButton#enhanceButton:disabled {{
        background-color: {BG_SECONDARY.name()};
        color: {TEXT_MUTED.name()};
        border: 1px solid {BORDER_SUBTLE.name()};
    }}
"""


def _read(widget):
    if isinstance(widget, NoWheelDropdown):
        return widget.currentData()
    return widget.value()


def _fill(widget, value) -> None:
    if isinstance(widget, NoWheelDropdown):
        choose_option(widget, str(value))
    elif isinstance(widget, NoWheelSpinBox):
        widget.setValue(int(value))
    else:
        widget.setValue(float(value))


def _enhancer_param_defs() -> dict:
    return {
        pd.key: pd
        for pd in WORKFLOW_REGISTRY[ENHANCE_WORKFLOW].param_definitions()
    }


def _settings_dragged(mime, _source) -> tuple[dict] | None:
    params = params_from_mime(mime)
    return None if params is None else (params,)


def _set_of_tick_and_number(tick, label, number) -> QFrame:
    column = QFrame()
    grid = QGridLayout(column)
    border_as_a_set(column, grid)
    grid.setSpacing(GAP_SMALL)
    grid.addWidget(tick, 0, 1, Qt.AlignmentFlag.AlignCenter)
    grid.addWidget(label, 1, 0)
    grid.addWidget(number, 1, 1)
    return column


class _SettingsScroll(QScrollArea):
    """The settings, scrolling down once the pane is squeezed shorter than they are, and sideways once it is squeezed narrower.

    Qt's own scroll area asks for their height as though nothing in them had wrapped."""

    def __init__(self, settings: QWidget):
        super().__init__()
        self.setObjectName("enhanceSettings")
        self.setWidget(settings)
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.Shape.NoFrame)

    def sizeHint(self) -> QSize:
        settings = self.widget()
        narrowest = settings.minimumSizeHint().width()
        laid_out = self.testAttribute(Qt.WidgetAttribute.WA_Resized)
        width = self.viewport().width() if laid_out else settings.sizeHint().width()
        height = settings.heightForWidth(max(width, narrowest))
        if width < narrowest:
            height += self.horizontalScrollBar().sizeHint().height()
        return QSize(settings.sizeHint().width(), height)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if event.size().width() != event.oldSize().width():
            self.updateGeometry()


class EnhancePane(QWidget):
    enhance_requested = pyqtSignal()
    fix_training_requested = pyqtSignal(str)
    preset_saved = pyqtSignal(str)
    preset_renamed = pyqtSignal(int, str)

    def __init__(self, on_change, parent=None, *, trash=trashed):
        super().__init__(parent)
        self._on_change = on_change
        self._trash = trash
        self._fix_training: dict[str, str] = {}
        self._picked: list[dict] = []
        self._folder = None
        self._source_models: frozenset[str] | object | None = _NOT_READ
        self._loading = False
        self._widgets: dict = {}
        self._defs = _enhancer_param_defs()
        self.setObjectName("enhancePane")
        self.setStyleSheet(_DISABLED_CSS + _FIX_FIELD_CSS + _ENHANCE_BUTTON_CSS)

        column = QVBoxLayout(self)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(GAP_SMALL)
        title_row = QHBoxLayout()
        title_row.setContentsMargins(0, 0, 0, 0)
        heading = QLabel("Enhance")
        heading.setStyleSheet("font-weight: bold;")
        title_row.addWidget(heading)
        title_row.addStretch(1)
        self._auto = ToggleSwitch()
        self._auto.setToolTip(_AUTO_TOOLTIP)
        self._auto.toggled.connect(self._emit)
        title_row.addWidget(self._auto)
        column.addLayout(title_row)

        column.addWidget(self._build_the_settings(), 1)

        self._enhance_button = QPushButton("Enhance")
        self._enhance_button.setObjectName("enhanceButton")
        self._enhance_button.clicked.connect(self.enhance_requested)
        self._presets: list[Preset] = []
        self._preset_dropdown = NoWheelDropdown()
        self._preset_dropdown.floor_chars = 2
        self._preset_dropdown.setPlaceholderText("(custom)")
        self._preset_dropdown.setToolTip("Pick a preset to use its settings")
        self._preset_dropdown.activated.connect(
            lambda index: self._take_settings(self._presets[index].params))
        self._preset_button = QPushButton("Save…")
        self._preset_button.clicked.connect(self._name_the_settings)
        action_row = QHBoxLayout()
        action_row.setContentsMargins(0, 0, 0, 0)
        action_row.addWidget(self._preset_dropdown, 1)
        action_row.addWidget(self._preset_button)
        action_row.addWidget(self._enhance_button)
        column.addLayout(action_row)
        DropTarget(self, _settings_dragged, self._take_settings)

    def _build_the_settings(self) -> QWidget:
        settings = QWidget()
        settings_column = QVBoxLayout(settings)
        settings_column.setContentsMargins(0, 0, 0, 0)
        settings_column.setSpacing(GAP_SMALL)
        self._model = NoWheelDropdown()
        offer_options(self._model, [MATCH_SOURCE_MODEL, *self._options("checkpoint")])
        self._model.currentIndexChanged.connect(self._emit)
        self._model.setToolTip(
            "Which model does the refining. Left at "
            f"\"{MATCH_SOURCE_MODEL}\" each image is enhanced by whatever made "
            "it, so it stays in its own style; pick one to pin it instead."
        )
        self._widgets["checkpoint"] = self._model
        self._model_warning = WarningMark()
        self._model_warning.unsetCursor()

        self._upscaler = NoWheelDropdown()
        offer_options(self._upscaler, self._options("upscale_model"))
        self._upscaler.currentIndexChanged.connect(self._emit)
        self._upscaler.setToolTip(param_help("upscale_model"))
        self._widgets["upscale_model"] = self._upscaler

        self._scale = self._number("enhance_scale", NoWheelDoubleSpinBox())
        self._steps = self._number("enhance_steps", NoWheelSpinBox())
        self._denoise = self._number("enhance_denoise", NoWheelDoubleSpinBox())
        model_caption = self._labeled("Model", self._model)
        settings_column.addLayout(FieldGrid(
            dropdowns=[(model_caption, self._model),
                     (self._labeled("Upscaler", self._upscaler), self._upscaler)],
            numbers=[(self._labeled(label, widget), widget)
                     for label, widget in (("Scale", self._scale), ("Steps", self._steps),
                                           ("Redraw Amount", self._denoise))],
            marks={model_caption: self._model_warning},
        ))

        fix_heading = QLabel("Fixes")
        fix_heading.setToolTip(param_help("enhance_detail_fixes"))
        settings_column.addWidget(fix_heading)
        settings_column.addWidget(self._fix_row())
        settings_column.addStretch(1)
        return _SettingsScroll(settings)

    def _fix_row(self) -> QWidget:
        host = QWidget()
        flow = FlowLayout(host, spacing=4)
        # Qt offers a layout's height-for-width only when the widget's policy says it has one.
        policy = host.sizePolicy()
        policy.setHeightForWidth(True)
        host.setSizePolicy(policy)
        self._fixes = {}
        self._fix_checks = {}
        self._fix_prompt_buttons = {}
        self._fix_prompts = {}
        self._fix_prompt_windows = {}
        self._fixes_that_can_run = [part.name for part in part_table()
                                    if detector_for_part(part) is not None]
        flow.addWidget(self._all_fixes_field())
        for part in part_table():
            flow.addWidget(self._fix_field(part))
        self._show_all_fixes()
        return host

    def _all_fixes_field(self) -> QWidget:
        tick = TickControl("")
        tick.setToolTip(_ALL_FIXES_TOOLTIP)
        tick.clicked.connect(self._tick_every_fix)
        number = self._fix_number()
        number.setToolTip(_ALL_FIXES_TOOLTIP)
        number.setKeyboardTracking(False)
        number.setMinimum(number.minimum() - number.singleStep())
        number.setSpecialValueText(" ")
        number.valueChanged.connect(self._number_every_fix)
        label = self._labeled("All", number)
        self._all_fixes_tick, self._all_fixes_number = tick, number
        if not self._fixes_that_can_run:
            for one in (tick, number, label):
                one.setEnabled(False)

        return _set_of_tick_and_number(tick, label, number)

    def _tick_every_fix(self, on: bool) -> None:
        self._change_every_fix(lambda name: self._fix_checks[name].setChecked(on))

    def _number_every_fix(self, value: float) -> None:
        if value == self._all_fixes_number.minimum():
            self._show_all_fixes()
        else:
            self._change_every_fix(lambda name: self._fixes[name].setValue(value))

    def _change_every_fix(self, change) -> None:
        self._loading = True
        try:
            for name in self._fixes_that_can_run:
                change(name)
        finally:
            self._loading = False
        self._emit()

    def _show_all_fixes(self) -> None:
        names = self._fixes_that_can_run
        self._all_fixes_tick.setChecked(
            bool(names) and all(self._fix_checks[name].isChecked() for name in names))
        numbers = {self._fixes[name].value() for name in names}
        number = self._all_fixes_number
        with QSignalBlocker(number):
            number.setValue(numbers.pop() if len(numbers) == 1 else number.minimum())

    def _fix_field(self, part) -> QWidget:
        check = TickControl("")
        check.setToolTip(param_help("enhance_detail_fixes"))
        widget = self._fix_number()
        widget.valueChanged.connect(self._emit)
        label = self._labeled(part.name.capitalize(), widget)
        prompts_button = fill_square_with_icon(QToolButton(), size=BUTTON_SIZE_HUD)
        prompts_button.setIcon(qt_icon("pencil"))
        prompts_button.setToolTip(param_help("enhance_fix_prompts"))
        prompts_button.clicked.connect(lambda _on=False, name=part.name: self.open_fix_prompts(name))
        if detector_for_part(part) is None:
            reason = _NO_DETECTOR_TOOLTIP.format(part.name, part.matches[0],
                                                 detector_folder(part))
            check.setEnabled(False)
            prompts_button.setEnabled(False)
            for one in (check, widget, label, prompts_button):
                one.setToolTip(reason)
        check.toggled.connect(lambda _on, name=part.name: self._fix_toggled(name))

        column = _set_of_tick_and_number(check, label, widget)
        column.layout().addWidget(prompts_button, 0, 0, Qt.AlignmentFlag.AlignCenter)

        self._fixes[part.name] = widget
        self._fix_checks[part.name] = check
        self._fix_prompt_buttons[part.name] = prompts_button
        self._show_fix_on(part.name)
        return column

    def open_fix_prompts(self, name: str) -> None:
        part = part_named(name)
        open_already = self._fix_prompt_windows.get(name)
        if open_already is not None:
            open_already.raise_()
            open_already.activateWindow()
            return
        current = fix_prompts_of(part, self._fix_prompts.get(part.name))
        loras = list_lora_files([NO_LORA], accepts=ENHANCE_MODEL_FAMILIES, fix=part.name)
        window = FixPromptsDialog(self, part, current, loras)
        window.accepted.connect(lambda: self._keep_fix_prompts(part.name, window.prompts()))
        window.finished.connect(lambda _result: self._fix_prompt_windows.pop(part.name, None))
        window.finished.connect(window.deleteLater)
        window.training.train_requested.connect(
            lambda: self.fix_training_requested.emit(part.name))
        window.trash_requested.connect(lambda: self._trash_fix_lora(part, window))
        window.show_training(self._fix_training.get(part.name))
        self._fix_prompt_windows[part.name] = window
        window.show_over_parent()

    def _trash_fix_lora(self, part, window) -> None:
        lora = window.picked_lora()
        if not self._trash(lora, window):
            return
        in_its_place = window.stop_offering(lora)
        kept = fix_prompts_of(part, self._fix_prompts.get(part.name))
        if kept["lora"] == lora:
            self._keep_fix_prompts(part.name, dict(
                kept, lora=in_its_place.fix, prompt=in_its_place.prompt_after(kept["prompt"])))

    def _keep_fix_prompts(self, name: str, prompts: dict) -> None:
        self._fix_prompts[name] = prompts
        self._emit()

    def show_fix_training(self, name: str, text: str | None) -> None:
        if text is None:
            self._fix_training.pop(name, None)
        else:
            self._fix_training[name] = text
        window = self._fix_prompt_windows.get(name)
        if window is not None:
            window.show_training(text)

    def use_fix_lora(self, name: str, lora: str) -> None:
        part = part_named(name)
        self._keep_fix_prompts(name, dict(fix_prompts_of(part, self._fix_prompts.get(name)),
                                          lora=lora))
        window = self._fix_prompt_windows.get(name)
        if window is not None:
            window.choose_lora(lora)

    def _fix_toggled(self, name: str) -> None:
        self._show_fix_on(name)
        self._emit()

    def _show_fix_on(self, name: str) -> None:
        check = self._fix_checks[name]
        widget = self._fixes[name]
        on = check.isChecked() and check.isEnabled()
        widget.setEnabled(on)
        label = self._label_for(widget)
        if label is not None:
            label.setEnabled(on)

    def _fix_number(self) -> NoWheelDoubleSpinBox:
        """One part's denoise spinner, sized to its digits because Qt's own hint for a spinner is two and a half times 0.00."""
        widget = NoWheelDoubleSpinBox()
        pd = self._defs.get("enhance_detail_fixes")
        widget.setMinimum(pd.min_val if pd is not None else 0.0)
        widget.setMaximum(pd.max_val if pd is not None else 1.0)
        widget.setSingleStep(pd.step if pd is not None and pd.step else 0.05)
        widget.setDecimals(2)
        widget.setValue(DEFAULT_FIX_DENOISE)
        widget.setButtonSymbols(NoWheelDoubleSpinBox.ButtonSymbols.NoButtons)
        widget.setObjectName("fixField")
        widget.setFixedWidth(widget.fontMetrics().horizontalAdvance("0.00")
                             + _FIX_FIELD_CHROME)
        widget.setToolTip(param_help("enhance_detail_fixes"))
        return widget

    def show_presets(self, presets: list[Preset]) -> None:
        self._presets = list(presets)
        self._preset_dropdown.clear()
        self._preset_dropdown.addItems([preset.name for preset in presets])
        open_the_list_in_full(self._preset_dropdown)
        self._show_the_preset_held()

    def _name_the_settings(self) -> None:
        held = self._preset_dropdown.currentIndex()
        title, given = (("Save Preset", "") if held < 0
                        else ("Rename Preset", self._presets[held].name))
        name, ok = QInputDialog.getText(self, title, "Preset name:", text=given)
        if not ok or not name.strip():
            return
        if held < 0:
            self.preset_saved.emit(name.strip())
        else:
            self.preset_renamed.emit(held, name.strip())

    def _show_the_preset_held(self) -> None:
        held = enhance_presets.matching(self._presets, self.settings().params)
        self._preset_dropdown.setCurrentIndex(-1 if held is None else held)
        text, tip = (("Save…", "Save these settings as a preset") if held is None
                     else ("Rename…", "Rename this preset"))
        self._preset_button.setText(text)
        self._preset_button.setToolTip(tip)

    def set_applicable(self, applicable: bool, reason: str = "") -> None:
        self.setEnabled(applicable)
        self.setToolTip("" if applicable else reason)

    def show_offer(self, available: bool, tip: str) -> None:
        self._enhance_button.setEnabled(available)
        self._enhance_button.setToolTip(tip)

    def _label_for(self, widget) -> QLabel | None:
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
        label = QLabel(text)
        label.setToolTip(widget.toolTip())
        return label

    def _options(self, key: str) -> list:
        pd = self._defs.get(key)
        return list(pd.options or []) if pd is not None else []

    def _number(self, key: str, widget):
        pd = self._defs.get(key)
        if pd is not None:
            widget.setMinimum(pd.min_val if pd.min_val is not None else 0)
            widget.setMaximum(pd.max_val if pd.max_val is not None else 999999)
            if pd.step:
                widget.setSingleStep(pd.step)
            if isinstance(widget, NoWheelDoubleSpinBox):
                widget.setDecimals(2)
            widget.setValue(pd.default)
        widget.setToolTip(definition_help(pd) if pd is not None else param_help(key))
        widest = max(widget.textFromValue(widget.minimum()),
                     widget.textFromValue(widget.maximum()), key=len)
        widget.setMinimumWidth(widget.fontMetrics().horizontalAdvance(widest)
                               + _NUMBER_FIELD_CHROME)
        widget.valueChanged.connect(self._emit)
        self._widgets[key] = widget
        return widget

    def show_settings(self, settings: EnhanceSettings) -> None:
        self._loading = True
        try:
            self._auto.setChecked(settings.auto)
            for key, widget in self._widgets.items():
                value = settings.params.get(key)
                if value is not None:
                    _fill(widget, value)
            self._fix_prompts = dict(settings.params.get("enhance_fix_prompts") or {})
            fixes = detail_fixes_of(settings.params)
            for name, widget in self._fixes.items():
                widget.setValue(float(fixes.get(name, DEFAULT_FIX_DENOISE)))
                self._fix_checks[name].setChecked(name in fixes)
                self._show_fix_on(name)
        finally:
            self._loading = False
        self._show_all_fixes()
        self._show_the_preset_held()
        self._warn_of_a_fixs_lora_trained_on_another_model()

    def show_images_in_front(self, picked, folder=None) -> None:
        self._picked, self._folder, self._source_models = list(picked), folder, _NOT_READ
        self._warn_of_a_fixs_lora_trained_on_another_model()

    def _warn_of_a_fixs_lora_trained_on_another_model(self) -> None:
        self._model_warning.warn(self._fix_lora_model_warning())

    def _fix_lora_model_warning(self) -> str:
        params = self.settings().params
        trained = {name: model for name, own in fix_prompts(params).items() if own["lora"]
                   if (model := fix_training.trained_on(own["lora"]))}
        if not trained:
            return ""
        held = params.get("checkpoint")
        return fix_lora_model_warning(self._models_it_runs(held), trained,
                                      self._options("checkpoint"),
                                      matching_the_source=held == MATCH_SOURCE_MODEL)

    def _models_it_runs(self, held) -> frozenset[str] | None:
        if held != MATCH_SOURCE_MODEL:
            return frozenset({held})
        if self._source_models is _NOT_READ:
            self._source_models = (models_matching_the_sources(self._picked) if self._picked
                                   else models_matching_a_folders_sources(self._folder))
        return self._source_models

    def settings(self) -> EnhanceSettings:
        params = {}
        for key in ENHANCE_SETTING_KEYS:
            widget = self._widgets.get(key)
            if widget is not None:
                params[key] = _read(widget)
        params["enhance_detail_fixes"] = {
            name: widget.value() for name, widget in self._fixes.items()
            if self._fix_checks[name].isChecked()
        }
        params["enhance_fix_prompts"] = dict(self._fix_prompts)
        return EnhanceSettings(auto=self._auto.isChecked(), params=params)

    def _emit(self, *_args):
        if not self._loading:
            self._show_all_fixes()
            self._show_the_preset_held()
            self._warn_of_a_fixs_lora_trained_on_another_model()
            self._on_change(self.settings())

    def _take_settings(self, params: dict) -> None:
        self.show_settings(EnhanceSettings(auto=self._auto.isChecked(), params=full_settings(params)))
        self._emit()


class FixPromptsDialog(QDialog):
    trash_requested = pyqtSignal()

    def __init__(self, parent, part, current: dict, loras: list[str]):
        super().__init__(parent, Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint)
        self._part = part
        self._loras = loras
        self.setWindowModality(Qt.WindowModality.NonModal)
        self.setWindowTitle(f"{part.name.capitalize()} fix prompts")
        layout = window_column(self)
        positive = prompt_boxes("positive_prompt", current["prompt"])
        self.positive = positive
        self.negative = prompt_boxes("negative_prompt", current["avoid"])
        positive.opposes(self.negative)
        self.prompt_warning, self.lora_warning = WarningMark(), WarningMark()
        layout.addLayout(prompts_side_by_side(self.prompt_warning, positive, self.negative), 1)
        lora = lora_dropdown(loras, current["lora"])
        self.lora = lora
        lora.currentIndexChanged.connect(self._explain_lora)
        self._explain_lora()
        self.strength = strength_box(current["strength"])
        training = TrainingControls()
        self.training = training
        self._running: str | None = None
        self._offer_training()
        lora.currentIndexChanged.connect(self._offer_training)
        training.trash_requested.connect(self.trash_requested)
        layout.addLayout(foot_row(self.lora_warning, lora, self.strength, training,
                                  ok_and_cancel(self)))
        positive.textChanged.connect(self._warn_about_the_lora)
        lora.currentIndexChanged.connect(self._warn_about_the_lora)
        for mark in (self.prompt_warning, self.lora_warning):
            mark.pressed.connect(self._resolve_the_lora_warning)
        self._warn_about_the_lora()

    def _missing_trigger_word(self):
        return trigger_word_advice({"positive_prompt": self.positive.value(),
                                    "lora": self.picked_lora()}, ("lora",)).get("lora")

    def picked_lora(self):
        return self.lora.currentData()

    def _in_place_of_a_lost_lora(self):
        return lost_lora_advice(self.picked_lora(), self._loras)

    def _warn_about_the_lora(self) -> None:
        found = self._in_place_of_a_lost_lora() or self._missing_trigger_word()
        self.lora_warning.warn(found.said if found is not None else "")
        missing = self._missing_trigger_word()
        self.prompt_warning.warn(missing.said if missing is not None else "")

    def _resolve_the_lora_warning(self) -> None:
        lost = self._in_place_of_a_lost_lora()
        missing = self._missing_trigger_word()
        if lost is not None:
            self.choose_lora(lost.fix)
            self.positive.rewrite(lost.prompt_after)
        elif missing is not None:
            self.positive.rewrite(missing.fixed)

    def stop_offering(self, lora: str):
        self._loras = [option for option in self._loras if option != lora]
        in_its_place = self._in_place_of_a_lost_lora()
        self._resolve_the_lora_warning()
        self.lora.removeItem(self.lora.findData(lora))
        return in_its_place

    def show_training(self, text: str | None) -> None:
        self._running = text
        self._offer_training()

    def _offer_training(self) -> None:
        self.training.show_offer(fix_training.training_offer(self._part, self.picked_lora()),
                                 self._running)

    def event(self, event) -> bool:
        if event.type() == QEvent.Type.WindowActivate:
            self._offer_training()
        return super().event(event)

    def choose_lora(self, lora: str) -> None:
        choose_option(self.lora, lora)

    def _explain_lora(self) -> None:
        self.lora.setToolTip(with_training_date("", self.picked_lora()))

    def prompts(self) -> dict:
        return fix_prompts_of(self._part, {
            "prompt": self.positive.value(), "avoid": self.negative.value(),
            "lora": self.picked_lora(), "strength": self.strength.value()})

    def show_over_parent(self) -> None:
        for watched in (self.parentWidget(), self.parentWidget().window()):
            watched.installEventFilter(self)
        self._cover_parent()
        self.show()

    def eventFilter(self, watched, event):
        if event.type() in (QEvent.Type.Move, QEvent.Type.Resize):
            self._cover_parent()
        return super().eventFilter(watched, event)

    def _cover_parent(self) -> None:
        parent = self.parentWidget()
        self.setGeometry(QRect(parent.mapToGlobal(QPoint(0, 0)), parent.size()))

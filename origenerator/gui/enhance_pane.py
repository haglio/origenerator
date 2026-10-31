"""The app's enhancement settings, at the foot of the Gallery pane.

Enhancement is not one of the settings that decide which folder a generation
lands in — it is a finish applied to an image afterward — so it is deliberately
not on the Generate form beside Seed, Dimensions and Output. It lives here
instead, beside the OSR2 controls, and it is app-wide: whatever is set here is
what Enhance All runs with, what a single image's Enhance action runs with, and
— with the checkbox on — what every image the app newly generates receives as it
lands. It follows you rather than the folder, so it shows in the collections
(Latest, Favorites, Experiments) exactly as it does on a settings folder.

Editing writes straight back through ``on_change`` — there is no Apply button —
and the settings persist with the rest of the session state. Auto-enhance is a
bare switch on the title row rather than a labeled checkbox among the settings: it
is the pane's power, not one of its settings.

An enhancement level dragged in from the Generate pane's version strip is absorbed:
the settings that made that version become the ones on the pane, so "do that
again" doesn't mean reading its numbers off and typing them back in.

Each part the detail pass can redraw is a tick and a denoise to run it
at: the checkbox is whether that part is fixed at all, so an unchecked part grays its
own name and number rather than making zero mean off. A part whose detector
isn't installed in ComfyUI can't be checked at all, and says why — the
alternative being a run that fails on submit.
"""
from __future__ import annotations

from PyQt6.QtCore import QEvent, QPoint, QRect, QSize, Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLayout,
    QPlainTextEdit,
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
from origenerator.gui.flow_layout import FlowLayout
from origenerator.gui.no_wheel import (
    NoWheelDoubleSpinBox,
    NoWheelDropdown,
    NoWheelSpinBox,
)
from origenerator.gui.panes import border_as_a_set
from origenerator.gui.param_fields import choose_option, offer_options
from origenerator.gui.param_help import definition_help, param_help, with_training_date
from origenerator.gui.prompt_boxes import PromptBoxes
from origenerator.gui.training_controls import TrainingControls
from origenerator.gui.warning_mark import WarningMark
from origenerator.prompt_tokens import prompt_reading
from origenerator.setting_advice import fix_lora_model_advice, trigger_word_advice
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
from origenerator.workflows.lora_rows import lora_strength
from origenerator.workflows.model_files import NO_LORA, list_lora_files

_NOT_READ = object()
_AUTO_TOOLTIP = (
    "Enhance every image generated from now on, as it lands — with the settings "
    "below. The original is kept, so an enhancement can always be compared "
    "against it or redone."
)


_NO_DETECTOR_TOOLTIP = (
    "Unavailable: ComfyUI hasn't got a model that finds {}. Install the Impact "
    "Subpack node pack, put one whose name says \"{}\" in its "
    "{} folder, and restart it."
)
# What a fix field costs around its digits: the padding either side below, its
# 1px border, and the pixels a spinner keeps for its cursor and its own inner
# margin. Measured by rendering one and looking, since a field a hair too narrow
# doesn't complain — it cuts a digit off 0.45, which still reads as a number.
_FIX_FIELD_PADDING = GAP_SMALL
_FIX_FIELD_CHROME = _FIX_FIELD_PADDING * 2 + 2 + 16
# The same for a number with its step buttons, measured the same way: at a few
# pixels less the last digit of 4.00 was cut.
_NUMBER_FIELD_CHROME = 50
# Disabling a widget is not the same as it looking disabled: the app's sheet
# colors every label, dropdown and spinner outright and names no disabled state,
# so a pane switched off went on reading exactly as live as before. These mute
# this pane's own fields — set on the pane, so nothing outside it is touched.
# (The auto switch is the exception: it paints itself, and dims itself.)
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
    """What one field reads as, in the type its param is stored as."""
    if isinstance(widget, NoWheelDropdown):
        return widget.currentData()
    return widget.value()


def _fill(widget, value) -> None:
    """Put a stored value into one field, coercing what JSON handed back."""
    if isinstance(widget, NoWheelDropdown):
        choose_option(widget, str(value))
    elif isinstance(widget, NoWheelSpinBox):
        widget.setValue(int(value))
    else:
        widget.setValue(float(value))


def _enhancer_param_defs() -> dict:
    """The standalone enhancer's own setting definitions, keyed by param — so this
    pane's ranges, steps and option lists can't drift from the workflow's.

    Read once per pane: ``param_definitions`` scans the model directories, and
    every field here would otherwise pay for that scan again.
    """
    return {
        pd.key: pd
        for pd in WORKFLOW_REGISTRY[ENHANCE_WORKFLOW].param_definitions()
    }


def _narrowest(widget: QWidget) -> int:
    return widget.minimumWidth() or widget.minimumSizeHint().width()


class _FieldGrid(QGridLayout):
    """Fields beside one column of captions, its warning marks in a column left of
    it: a dropdown to a line, and the numbers sharing a line while each keeps its
    width, a line each when they cannot.

    A layout rather than a widget, because Qt asks a widget's layout for its
    height at a width and never the widget itself."""

    def __init__(self, dropdowns: list[tuple[QLabel, QWidget]],
                 numbers: list[tuple[QLabel, QWidget]], marks: dict[QLabel, WarningMark]):
        super().__init__()
        self._dropdowns = dropdowns
        self._numbers = numbers
        self._marks = marks
        self.setContentsMargins(0, 0, 0, 0)
        self.setSpacing(GAP_SMALL)
        self._stacked: bool | None = None
        self._arrange(stacked=False)

    def hasHeightForWidth(self) -> bool:
        return True

    def heightForWidth(self, width: int) -> int:
        lines = [[pair] for pair in self._dropdowns]
        if width < self._one_line_width():
            lines += [[pair] for pair in self._numbers]
        else:
            lines.append(self._numbers)
        heights = [max(max(label.sizeHint().height(), field.sizeHint().height())
                       for label, field in line) for line in lines]
        return sum(heights) + (len(heights) - 1) * self.verticalSpacing()

    def sizeHint(self) -> QSize:
        width = self._one_line_width()
        return QSize(width, self.heightForWidth(width))

    def minimumSize(self) -> QSize:
        pairs = self._dropdowns + self._numbers
        narrowest = (self._mark_column()
                     + max(label.sizeHint().width() for label, _field in pairs)
                     + self.horizontalSpacing()
                     + max(_narrowest(field) for _label, field in pairs))
        return QSize(narrowest, self.heightForWidth(self._one_line_width()))

    def setGeometry(self, rect: QRect) -> None:
        self._arrange(stacked=rect.width() < self._one_line_width())
        super().setGeometry(rect)

    def _mark_column(self) -> int:
        return (max(mark.sizeHint().width() for mark in self._marks.values())
                + self.horizontalSpacing())

    def _one_line_width(self) -> int:
        captions = max(label.sizeHint().width()
                       for label, _field in self._dropdowns + self._numbers[:1])
        return (self._mark_column() + captions
                + sum(label.sizeHint().width() for label, _field in self._numbers[1:])
                + sum(_narrowest(field) for _label, field in self._numbers)
                + self.horizontalSpacing() * (2 * len(self._numbers) - 1))

    def _arrange(self, stacked: bool) -> None:
        if stacked == self._stacked:
            return
        for column in range(self.columnCount()):
            self.setColumnStretch(column, 0)
        span = 1 if stacked else 2 * len(self._numbers) - 1
        for row, (label, field) in enumerate(self._dropdowns):
            if label in self._marks:
                self.addWidget(self._marks[label], row, 0)
            self.addWidget(label, row, 1)
            self.addWidget(field, row, 2, 1, span)
        below = len(self._dropdowns)
        for index, (label, field) in enumerate(self._numbers):
            row, column = (below + index, 1) if stacked else (below, 1 + 2 * index)
            self.addWidget(label, row, column)
            self.addWidget(field, row, column + 1)
            self.setColumnStretch(column + 1, 1)
        self._stacked = stacked


def _settings_dragged(mime, _source) -> tuple[dict] | None:
    params = params_from_mime(mime)
    return None if params is None else (params,)


class _SettingsScroll(QScrollArea):
    """The settings, scrolling down once the pane is squeezed shorter than they
    are, and sideways once it is squeezed narrower.

    Asks for their whole height at the width it has: Qt's own scroll area asks
    for their height as though nothing in them had wrapped."""

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
    """The Enhance pane: an Auto checkbox over the settings an enhancement runs at.

    ``show_settings`` loads a stored configuration (or the defaults, before
    anything has been set); every edit calls back with the new
    :class:`~origenerator.gallery.enhance.EnhanceSettings`. The pane holds no
    state of its own beyond its fields — the gallery keeps the value and routes
    it where it's needed — so it stays a plain editor.
    """

    enhance_requested = pyqtSignal()
    fix_training_requested = pyqtSignal(str)
    preset_saved = pyqtSignal(str)
    preset_renamed = pyqtSignal(int, str)

    def __init__(self, on_change, parent=None):
        super().__init__(parent)
        self._on_change = on_change
        self._fix_training: dict[str, str] = {}
        self._picked: list[dict] = []
        self._folder = None
        self._source_models: frozenset[str] | object | None = _NOT_READ
        self._loading = False  # suppress the write-back while filling the fields
        self._widgets: dict = {}
        self._defs = _enhancer_param_defs()
        self.setObjectName("enhancePane")
        self.setStyleSheet(_DISABLED_CSS + _FIX_FIELD_CSS + _ENHANCE_BUTTON_CSS)

        column = QVBoxLayout(self)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(GAP_SMALL)
        # The title row, with the auto switch at its far right — a bare switch,
        # the way a pane's power is a switch on its corner rather than a line
        # of prose among its settings. What it does is in its tooltip; the
        # settings below are what it does it with.
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

        settings = QWidget()
        settings_column = QVBoxLayout(settings)
        settings_column.setContentsMargins(0, 0, 0, 0)
        settings_column.setSpacing(GAP_SMALL)
        self._model = NoWheelDropdown()
        # The default leaves the refining model to whatever made the image, which
        # is what keeps an enhanced image in its own style; picking a checkpoint
        # here overrides that for every enhance this folder runs.
        offer_options(self._model, [MATCH_SOURCE_MODEL, *self._options("checkpoint")])
        self._model.currentIndexChanged.connect(self._emit)
        self._model.setToolTip(
            "Which model does the refining. Left at "
            f"\"{MATCH_SOURCE_MODEL}\" each image is enhanced by whatever made "
            "it, so it stays in its own style; pick one to pin it instead."
        )
        self._widgets["checkpoint"] = self._model
        self._model_warning = WarningMark()
        self._model_warning.pressed.connect(self._use_the_model_a_fixs_lora_was_trained_on)

        self._upscaler = NoWheelDropdown()
        offer_options(self._upscaler, self._options("upscale_model"))
        self._upscaler.currentIndexChanged.connect(self._emit)
        self._upscaler.setToolTip(param_help("upscale_model"))
        self._widgets["upscale_model"] = self._upscaler

        self._scale = self._number("enhance_scale", NoWheelDoubleSpinBox())
        self._steps = self._number("enhance_steps", NoWheelSpinBox())
        self._denoise = self._number("enhance_denoise", NoWheelDoubleSpinBox())
        model_caption = self._labeled("Model", self._model)
        settings_column.addLayout(_FieldGrid(
            dropdowns=[(model_caption, self._model),
                     (self._labeled("Upscaler", self._upscaler), self._upscaler)],
            numbers=[(self._labeled(label, widget), widget)
                     for label, widget in (("Scale", self._scale), ("Steps", self._steps),
                                           ("Redraw Amount", self._denoise))],
            marks={model_caption: self._model_warning},
        ))

        # The detail pass: a tick and a number per part it can be aimed at, the
        # number being the denoise that part is redrawn at. Their denoise is
        # separate from the one above, and from each other's, because it can
        # afford to be far bolder: nothing outside the regions a detector finds
        # is touched, and a mouth wants a harder redraw than a face does.
        fix_heading = QLabel("Fixes")
        fix_heading.setToolTip(param_help("enhance_detail_fixes"))
        settings_column.addWidget(fix_heading)
        settings_column.addWidget(self._fix_row())
        settings_column.addStretch(1)
        column.addWidget(_SettingsScroll(settings), 1)

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
        DropTarget(self, _settings_dragged, self._take_settings)  # a version's, dragged here

    def _fix_row(self) -> QWidget:
        """Every fixable part on one line: a tick over its name and the
        denoise it runs at.

        The checkbox is what turns a part's fix on, so the number underneath is free
        to sit at the denoise it would run at whether or not it is running —
        check a part and it fixes at that, uncheck it and the number is still
        there for next time, grayed along with the name so the line reads at a
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
        Each part's checkbox, name and number travel together, so a wrap can't
        separate them.

        Every part the app knows is here, installed detector or not: one with
        nothing to find it can't be checked, and says which file to add — which
        tells you more than an absent field (nothing at all to see) and far
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
        self._fix_prompt_buttons = {}
        self._fix_prompts = {}
        self._fix_prompt_windows = {}
        for part in part_table():
            flow.addWidget(self._fix_field(part))
        return host

    def _fix_field(self, part) -> QWidget:
        """One part's column: its checkbox, over its name and its denoise."""
        check = TickControl("")
        check.setToolTip(param_help("enhance_detail_fixes"))
        widget = self._fix_number()
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

        column = QFrame()
        grid = QGridLayout(column)
        border_as_a_set(column, grid)
        grid.setSpacing(GAP_SMALL)
        grid.addWidget(prompts_button, 0, 0, Qt.AlignmentFlag.AlignCenter)
        grid.addWidget(check, 0, 1, Qt.AlignmentFlag.AlignCenter)
        grid.addWidget(label, 1, 0)
        grid.addWidget(widget, 1, 1)

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
        window.show_training(self._fix_training.get(part.name))
        self._fix_prompt_windows[part.name] = window
        window.show_over_parent()

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
        """A part switched on or off: gray its name and number to match, and
        report the settings the pane now reads as."""
        self._show_fix_on(name)
        self._emit()

    def _show_fix_on(self, name: str) -> None:
        """Gray one part's name and number unless it is checked."""
        check = self._fix_checks[name]
        widget = self._fixes[name]
        on = check.isChecked() and check.isEnabled()
        widget.setEnabled(on)
        label = self._label_for(widget)
        if label is not None:
            label.setEnabled(on)

    def _fix_number(self) -> NoWheelDoubleSpinBox:
        """One part's denoise spinner, ranged from the enhancer's own ParamDef so a
        floor of zero — the value that means "leave this part alone" — stays the
        workflow's answer rather than this pane's.

        Sized to the digits it shows: Qt's own hint for a spinner is two and a
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
        # The denoise a fix runs at unless it is given another: the checkbox beside
        # it is what says whether this part is fixed, so the number never has to
        # mean off, and a part checked on runs at something sensible untouched.
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
        """Switch the whole pane on or off, and look it.

        Off, every field is disabled *and* muted, so the pane reads as what it
        is where it can't apply — settings for an action that isn't on offer —
        rather than as live settings that quietly do nothing. Back on, each field
        returns to whatever it was in its own right: a part stays grayed if
        ComfyUI still hasn't got a detector that finds it.
        """
        self.setEnabled(applicable)
        self.setToolTip("" if applicable else reason)

    def show_offer(self, available: bool, tip: str) -> None:
        self._enhance_button.setEnabled(available)
        self._enhance_button.setToolTip(tip)

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
        """The installed files a dropdown offers, from the enhancer's own ParamDef."""
        pd = self._defs.get(key)
        return list(pd.options or []) if pd is not None else []

    def _number(self, key: str, widget):
        """One numeric setting, ranged from the enhancer's own ParamDef."""
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
        """Fill the pane from one folder's stored settings, writing nothing back.

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
            self._fix_prompts = dict(settings.params.get("enhance_fix_prompts") or {})
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
        self._show_the_preset_held()
        self._warn_of_a_fixs_lora_trained_on_another_model()

    def show_images_in_front(self, picked, folder=None) -> None:
        self._picked, self._folder, self._source_models = list(picked), folder, _NOT_READ
        self._warn_of_a_fixs_lora_trained_on_another_model()

    def _model_advice(self):
        params = self.settings().params
        trained = {name: model for name, own in fix_prompts(params).items() if own["lora"]
                   if (model := fix_training.trained_on(own["lora"]))}
        if not trained:
            return None
        held = params.get("checkpoint")
        return fix_lora_model_advice(held, self._models_it_runs(held), trained,
                                     self._options("checkpoint")).get("checkpoint")

    def _models_it_runs(self, held) -> frozenset[str] | None:
        if held != MATCH_SOURCE_MODEL:
            return frozenset({held})
        if self._source_models is _NOT_READ:
            self._source_models = (models_matching_the_sources(self._picked) if self._picked
                                   else models_matching_a_folders_sources(self._folder))
        return self._source_models

    def _warn_of_a_fixs_lora_trained_on_another_model(self) -> None:
        found = self._model_advice()
        self._model_warning.warn(found.said if found is not None else "")

    def _use_the_model_a_fixs_lora_was_trained_on(self) -> None:
        found = self._model_advice()
        if found is not None:
            _fill(self._model, found.fixed(self._model.currentData()))

    def settings(self) -> EnhanceSettings:
        """What the pane currently reads as."""
        params = {}
        for key in ENHANCE_SETTING_KEYS:
            widget = self._widgets.get(key)
            if widget is not None:
                params[key] = _read(widget)
        # Only the parts checked on: an unchecked part is one this enhancement
        # doesn't touch, and carrying its number anyway would make two settings
        # that fix the same parts compare as different.
        params["enhance_detail_fixes"] = {
            name: widget.value() for name, widget in self._fixes.items()
            if self._fix_checks[name].isChecked()
        }
        params["enhance_fix_prompts"] = dict(self._fix_prompts)
        return EnhanceSettings(auto=self._auto.isChecked(), params=params)

    def _emit(self, *_args):
        if not self._loading:
            self._show_the_preset_held()
            self._warn_of_a_fixs_lora_trained_on_another_model()
            self._on_change(self.settings())

    def _take_settings(self, params: dict) -> None:
        self.show_settings(EnhanceSettings(auto=self._auto.isChecked(), params=full_settings(params)))
        self._emit()


def _prompt_boxes(key: str, text: str) -> PromptBoxes:
    boxes = PromptBoxes(QPlainTextEdit)
    boxes.set_reading(prompt_reading(ENHANCE_WORKFLOW, {}, key))
    boxes.set_value(text)
    return boxes


def _side_by_side(*widgets) -> QWidget:
    host = QWidget()
    row = QHBoxLayout(host)
    row.setContentsMargins(0, 0, 0, 0)
    row.setSpacing(GAP_SMALL)
    for widget in widgets:
        row.addWidget(widget)
    return host


class FixPromptsDialog(QDialog):
    def __init__(self, parent, part, current: dict, loras: list[str]):
        super().__init__(parent, Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint)
        self._part = part
        self.setWindowModality(Qt.WindowModality.NonModal)
        self.setWindowTitle(f"{part.name.capitalize()} fix prompts")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(GAP_SMALL)
        layout.setSizeConstraint(QLayout.SizeConstraint.SetNoConstraint)
        heading = QLabel(self.windowTitle())
        heading.setStyleSheet("font-weight: bold;")
        layout.addWidget(heading)
        self.positive = _prompt_boxes("positive_prompt", current["prompt"])
        self.negative = _prompt_boxes("negative_prompt", current["avoid"])
        self.prompt_warning, self.lora_warning = WarningMark(), WarningMark()
        side_by_side = QHBoxLayout()
        for caption, field in (((self.prompt_warning, QLabel("Positive Prompt")), self.positive),
                               ((QLabel("Negative Prompt"),), self.negative)):
            column = QVBoxLayout()
            column.addWidget(_side_by_side(*caption), 0, Qt.AlignmentFlag.AlignLeft)
            column.addWidget(field, 1)
            side_by_side.addLayout(column)
        layout.addLayout(side_by_side, 1)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok
                                   | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        self.lora = NoWheelDropdown()
        offer_options(self.lora, loras)
        choose_option(self.lora, current["lora"] or NO_LORA)
        self.lora.currentIndexChanged.connect(self._explain_lora)
        self._explain_lora()
        strength = lora_strength("lora_strength", current["strength"])
        self.strength = NoWheelDoubleSpinBox()
        self.strength.setRange(strength.min_val, strength.max_val)
        self.strength.setSingleStep(strength.step)
        self.strength.setValue(strength.default)
        self.strength.setToolTip(definition_help(strength))
        self.training = TrainingControls()
        self._running: str | None = None
        self._offer_training()
        foot = FlowLayout(spacing=GAP_SMALL)
        for together in ((self.lora_warning, QLabel("LoRA"), self.lora),
                         (QLabel("LoRA Strength"), self.strength)):
            foot.addWidget(_side_by_side(*together))
        foot.addWidget(self.training)
        foot.add_trailing(buttons)
        layout.addLayout(foot)
        self.positive.textChanged.connect(self._warn_of_a_missing_trigger_word)
        self.lora.currentIndexChanged.connect(self._warn_of_a_missing_trigger_word)
        for mark in (self.prompt_warning, self.lora_warning):
            mark.pressed.connect(self._add_the_missing_trigger_word)
        self._warn_of_a_missing_trigger_word()

    def _missing_trigger_word(self):
        return trigger_word_advice({"positive_prompt": self.positive.value(),
                                    "lora": self.lora.currentData()}, ("lora",)).get("lora")

    def _warn_of_a_missing_trigger_word(self) -> None:
        missing = self._missing_trigger_word()
        for mark in (self.prompt_warning, self.lora_warning):
            mark.warn(missing.said if missing is not None else "")

    def _add_the_missing_trigger_word(self) -> None:
        missing = self._missing_trigger_word()
        if missing is not None:
            self.positive.rewrite(missing.fixed)

    def show_training(self, text: str | None) -> None:
        self._running = text
        self._offer_training()

    def _offer_training(self) -> None:
        self.training.show_offer(fix_training.training_offer(self._part), self._running)

    def event(self, event) -> bool:
        if event.type() == QEvent.Type.WindowActivate:
            self._offer_training()
        return super().event(event)

    def choose_lora(self, lora: str) -> None:
        choose_option(self.lora, lora)

    def _explain_lora(self) -> None:
        self.lora.setToolTip(with_training_date("", self.lora.currentData()))

    def prompts(self) -> dict:
        return fix_prompts_of(self._part, {
            "prompt": self.positive.value(), "avoid": self.negative.value(),
            "lora": self.lora.currentData(), "strength": self.strength.value()})

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

from __future__ import annotations

import json
import logging
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path

from PyQt6.QtCore import QPoint, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QAction, QIcon, QPixmap
from PyQt6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)
from shared_ui.colors import TEXT_PRIMARY, YELLOW
from shared_ui.icons import icon_then_text, qt_icon
from shared_ui.orientation import orientation_of_size as shape_of_size
from shared_ui.spacing import BUTTON_GAP, BUTTON_ROW_GAP, GAP_MEDIUM, MARGIN_STANDARD

from origenerator import (
    action_settings,
    evolver_export,
    gallery,
    request_settings,
    said_action,
)
from origenerator.comfyui_client import ComfyUIClient
from origenerator.config import (
    COMFYUI_INPUT_DIR,
    OUTPUT_PLACES,
    THUMB_DIR,
)
from origenerator.db import Database, NewSeedUse
from origenerator.export_lane import UNSEND_CAPTION, lane_for
from origenerator.gallery import (
    EnhanceSettings,
    config_folder_key,
    config_folder_name,
    describe_enhance_params,
    displayed_versions,
    enhance_params_for,
    media_type_of_row,
    output_file_path,
    prompts_differ_from,
    resolve_preview,
    settings_signature,
    version_matching_settings,
    workflow_output_type,
)
from origenerator.gallery.shapes import PORTRAIT
from origenerator.generation_config import (
    ConfigSnapshot,
    configs_match,
    merge_denormalized,
    would_reproduce_a_completed_run,
)
from origenerator.generation_state import made_here
from origenerator.gui import icons
from origenerator.gui.action_dropdown import ActionDropdown
from origenerator.gui.basic_section import BasicSection, wrappable
from origenerator.gui.combination import Combination
from origenerator.gui.corner_buttons import enhance_state
from origenerator.gui.drop_zone import DropZone, DropZones
from origenerator.gui.eliding import ElidingLabel
from origenerator.gui.enhance_versions import (
    Dating,
    EnhanceOffer,
    EnhanceVersions,
    RunningEnhancement,
)
from origenerator.gui.flow_layout import FlowLayout
from origenerator.gui.folder_modify import FolderModify
from origenerator.gui.generate_button import (
    DEFAULT_CAPTION,
    RANDOM_SEED_CAPTION,
    GenerateButton,
    refused_over_prompts,
)
from origenerator.gui.how_many import GenerateWithHowMany, HowManyDropdown
from origenerator.gui.inflight import ALREADY_MAKING_ONE_TIP, CANCEL_TEXT, cancel_tooltip
from origenerator.gui.label_cells import LabelCell, LabelForm
from origenerator.gui.lora_offers import LoraOffers
from origenerator.gui.message import set_marked_text
from origenerator.gui.no_wheel import NoWheelDropdown
from origenerator.gui.panes import PaneSplitter, pane, pane_border
from origenerator.gui.param_form import FormHelpers, ParamForm, WorkflowTraits
from origenerator.gui.related_media import RelatedLookups, RelatedMedia
from origenerator.gui.request_answering import RequestAnswerer
from origenerator.gui.viewport import Viewport
from origenerator.gui.warning_mark import WarningMark
from origenerator.gui.zone_items import ZoneFolders, ZoneItems
from origenerator.image_states import state_names
from origenerator.item_names import ItemNames
from origenerator.library_views import NO_VIEWS, LibraryViews, TabViews
from origenerator.media import MediaType
from origenerator.osr2_driver import drive_target_for
from origenerator.prompt_tokens import prompt_readings
from origenerator.regeneration import MADE_ELSEWHERE_TIP, workflow_gone
from origenerator.seed_history import SeedHistory, SeedUse, SeedUseKind, seed_history
from origenerator.setting_advice import (
    fresh_settings,
    named_models,
    not_installed,
    not_installed_advice,
    not_offered_advice,
    recommendations,
    recommended_choices,
    setting_advice,
    spoken_list,
    trigger_word_advice,
)
from origenerator.timing import estimate_label
from origenerator.workflows import RETIRED_WORKFLOW_NAMES, offered_workflows, workflow_named

logger = logging.getLogger(__name__)

_CAPTION_DELAY_MS = 250
_RANDOM_SEED_TIP = (
    "These settings have already been generated with this exact seed, so "
    "Generate draws a fresh one rather than re-creating the same file. "
    "Change a setting to generate something else instead."
)
_FLOOR_CAP = 330

_MODIFIED_MESSAGE = "(not yet generated with modifications)"

_WAITING_NOTE = "Waiting for preview…"

_MODIFY_GUARD = "Rewrite the prompt first"

_GO_TO_FOLDER_TIP = "Go to the folder this item is in"

@dataclass(frozen=True)
class _RequestAim:
    prompt_id: str
    shown: tuple[str, str]
    turns: list = field(default_factory=list)


def _nothing_to_start_from(missing_inputs: list[str]) -> str:
    named = spoken_list(missing_inputs, "and")
    article = "an" if named[:1].lower() in "aeiou" else "a"
    return f"Nothing to start from — pick {article} {named} first"


def _lost_workflow_note(workflow_name: str) -> str:
    retired = RETIRED_WORKFLOW_NAMES.get(workflow_name)
    made_with = (f"{retired}, which has been retired," if retired
                 else "a workflow Origenerator doesn't have,")
    return (f"This was made with {made_with} so no new ones can be made. "
            "Select a workflow above to make something new.")


def _select_a_workflow_first(workflow_name: str) -> str:
    return f"{workflow_gone(workflow_name)} — select a workflow first"


def _not_installed_note(names: list[str]) -> str:
    shown = named_models(names)
    if len(names) == 1:
        return (f"This was made with {shown}, which isn't installed anymore, so no new ones "
                "can be made with it until an installed one is picked in its place.")
    return (f"This was made with {shown}, which aren't installed anymore, so no new ones "
            "can be made with them until installed ones are picked in their place.")


def _pick_installed_ones_first(names: list[str]) -> str:
    shown = named_models(names)
    if len(names) == 1:
        return f"{shown} isn't installed anymore — pick an installed one first"
    return f"{shown} aren't installed anymore — pick installed ones first"


class GenerateTab(DropZones):
    title_changed = pyqtSignal(str)
    form_edited = pyqtSignal()
    user_edited = pyqtSignal()
    prompt_fields_changed = pyqtSignal()
    link_clicked = pyqtSignal(str)
    item_action_requested = pyqtSignal(str, str)
    context_menu_requested = pyqtSignal(str, QPoint)
    go_to_folder_requested = pyqtSignal(str)
    generate_requested = pyqtSignal(str, list)
    modify_requested = pyqtSignal(str, str, dict)
    cancel_requested = pyqtSignal()
    how_many_chosen = pyqtSignal(int)
    displayed_changed = pyqtSignal()
    enhance_requested = pyqtSignal(str)
    versions_delete_requested = pyqtSignal(str, list)
    train_requested = pyqtSignal(str)
    trash_requested = pyqtSignal(str)

    def __init__(self, client: ComfyUIClient | None, db: Database,
                 *, fun_time=None, inbox: evolver_export.EvolverInbox | None = None,
                 views: TabViews = NO_VIEWS):
        super().__init__()
        self._heights = views.heights
        self._inbox = inbox or evolver_export.default_inbox()
        self._client = client
        self._db = db
        self._library = views.library or LibraryViews(db)
        self._names = views.names or ItemNames(db)
        self._animated_preview = views.animated_preview or (
            lambda row: gallery.animated_preview_if_made(row, OUTPUT_PLACES, THUMB_DIR))
        self._param_form: ParamForm | None = None
        self._generating = False
        self._making_one = None
        self._launched_runs: dict[str, dict | None] = {}
        self._watched_key: str | None = None
        self._live_note: str | None = None
        self._live_source: Combination | None = None
        self._displayed_row: dict | None = None
        self._pending_enhancement: RunningEnhancement | None = None
        self._enhance_settings = EnhanceSettings()
        self._displayed_config: ConfigSnapshot | None = None
        self._folder_modify: FolderModify | None = None
        self._settings_source: tuple[str, str | None, str] = ("", None, "")
        self._source_video_row: dict | None = None
        self.lora_offers = LoraOffers(lambda: self._param_form,
                                      lambda: workflow_named(self._form_workflow_key),
                                      train=self.train_requested.emit,
                                      trash=self.trash_requested.emit)
        self._caption_timer = QTimer(self)
        self._caption_timer.setSingleShot(True)
        self._caption_timer.setInterval(_CAPTION_DELAY_MS)
        self._caption_timer.timeout.connect(self._apply_generate_caption)
        self._fun_time = fun_time
        self._loading_config = 0
        self._fresh_form = False
        self._form_checkpoint = None
        self._autoshow_held = False
        self._request_aim: _RequestAim | None = None
        self._asked = 0
        self._requests = views.requests or RequestAnswerer(db, None, client, parent=self)
        self._go_to_folder = QAction("Go to folder", self)
        self._go_to_folder.setToolTip(_GO_TO_FOLDER_TIP)
        self._go_to_folder.setVisible(False)
        self._go_to_folder.triggered.connect(self._on_go_to_folder)
        self._can_go_to_folder = None
        self._build_ui()

    @contextmanager
    def _loading(self):
        self._loading_config += 1
        try:
            yield
        finally:
            self._loading_config -= 1

    def _note_user_edit(self):
        if not self._loading_config:
            self.user_edited.emit()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, MARGIN_STANDARD, 0, MARGIN_STANDARD)
        self._build_viewport()
        body = self._build_body_scroll()
        header = LabelForm()
        self._build_saved_generation_block(body, header)
        self._build_workflow_header(body, header)
        self._build_related_media(body)
        body.addStretch(1)
        self._settings_pane = self._build_settings_pane()
        self._media_split.addWidget(self._settings_pane)
        self._media_split.hold_still(self._fun_time is not None)
        layout.addWidget(self._media_split, 1)
        self._media_side_by_side = False
        self._media_border: list[int] | None = None
        self._on_workflow_changed()

    def _build_viewport(self) -> Viewport:
        self._viewport = Viewport(show_scrubber=True)
        self._viewport.action_triggered.connect(self.item_action_requested)
        self._viewport.context_requested.connect(self.context_menu_requested)
        self._media_split = PaneSplitter(Qt.Orientation.Vertical)
        self._viewport_pane, viewport_column = pane()
        viewport_column.setContentsMargins(MARGIN_STANDARD, 0, MARGIN_STANDARD, 0)
        viewport_column.addWidget(self._viewport)
        self._media_split.addWidget(self._viewport_pane)
        self._viewport.media_resized.connect(self._reflow_for_the_media)
        return self._viewport

    def _build_body_scroll(self) -> QVBoxLayout:
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        body_host = QWidget()
        body = QVBoxLayout(body_host)
        body.setContentsMargins(MARGIN_STANDARD, MARGIN_STANDARD,
                                MARGIN_STANDARD, 0)
        body.setSpacing(GAP_MEDIUM)
        self._scroll.setWidget(body_host)
        return body

    def _build_saved_generation_block(self, body: QVBoxLayout, header: LabelForm) -> None:
        self._basic_section = BasicSection(go_to_folder=self._go_to_folder)
        self._basic_section.hide()
        body.addWidget(self._basic_section)
        self._action = ActionDropdown(state_names(), action_settings.CATEGORIES, header)
        self._action.chosen.connect(self._on_action_chosen)

    def _on_action_chosen(self, prompt_id: str, said: str) -> None:
        said_action.say(self._db, prompt_id, self._displayed_row or {}, said)

    def _build_workflow_header(self, body: QVBoxLayout, header: LabelForm) -> None:
        self._form_workflow_key = None
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(GAP_MEDIUM)
        header.setLabelAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        )
        self._workflow_dropdown = NoWheelDropdown()
        self._workflow_dropdown.setPlaceholderText("Select a workflow…")
        self._offer_workflows(makes=None, holding=None)
        self._workflow_dropdown.currentIndexChanged.connect(self._on_workflow_changed)
        self._workflow_dropdown.currentIndexChanged.connect(self._note_user_edit)
        self._workflow_warning = WarningMark()
        self._workflow_warning.pressed.connect(self._resolve_every_warning)
        header.addRow(LabelCell(self._workflow_warning, ElidingLabel("Workflow"),
                                header.label_column),
                      self._workflow_dropdown)
        body.addLayout(header)
        self._cannot_remake_note = QLabel()
        self._cannot_remake_note.setObjectName("cannotRemakeNote")
        self._cannot_remake_note.setWordWrap(True)
        self._cannot_remake_note.hide()
        body.addWidget(self._cannot_remake_note)
        self._estimate_label = QLabel()
        self._estimate_label.setObjectName("estimateLabel")
        self._estimate_label.setWordWrap(True)
        body.addWidget(self._estimate_label)
        self._form_host = QWidget()
        self._form_host_column = QVBoxLayout(self._form_host)
        self._form_host_column.setContentsMargins(0, 0, 0, 0)
        body.addWidget(self._form_host)

    def _build_related_media(self, body: QVBoxLayout) -> None:
        self._related = RelatedMedia(RelatedLookups(
            video_rows=self._video_rows,
            row_of=self._db.get_generation,
            held_rows=lambda: self._library.now().held_rows,
            name_of=self._names.of, animated_preview=self._animated_preview,
            request_of=self._db.get_request,
            requests_about=self._db.requests_about))
        self._related.link_clicked.connect(self.link_clicked)
        body.addWidget(self._related)
        self._versions = EnhanceVersions()
        self._listed_versions = []
        self._versions.version_selected.connect(self._show_version)
        self._versions.enhance_requested.connect(self._on_enhance_requested)
        self._versions.delete_requested.connect(self._on_versions_delete_requested)
        body.addWidget(self._versions)

    def _build_settings_pane(self) -> QWidget:
        settings_pane = QWidget()
        column = QVBoxLayout(settings_pane)
        column.setContentsMargins(0, MARGIN_STANDARD, 0, 0)
        column.setSpacing(0)
        buttons = self._build_button_row()
        buttons.setContentsMargins(MARGIN_STANDARD, 0, MARGIN_STANDARD, MARGIN_STANDARD)
        column.addLayout(buttons)
        self._settings_border = pane_border()
        column.addWidget(self._settings_border)
        column.addWidget(self._scroll, 1)
        return settings_pane

    def _build_button_row(self) -> FlowLayout:
        btn_row = FlowLayout(spacing=BUTTON_GAP, row_spacing=BUTTON_ROW_GAP,
                             align_right=True)
        self._lane_button = QPushButton()
        self._lane_button.clicked.connect(
            lambda _checked=False: self._on_send(self._offered_lane))
        btn_row.addWidget(self._lane_button)
        self._sent_row = self._build_sent_row()
        btn_row.addWidget(self._sent_row)
        self._offered_lane = None
        self._update_lane_button(None)
        self._cancel_btn = QPushButton(CANCEL_TEXT)
        self._cancel_btn.setObjectName("cancelBtn")
        self._cancel_btn.clicked.connect(self.cancel_requested)
        self._cancel_btn.hide()
        self._generate_btn = GenerateButton()
        self._generate_btn.clicked.connect(self._on_generate)
        self._how_many = HowManyDropdown()
        self._how_many.chosen.connect(self.how_many_chosen)
        btn_row.addWidget(self._cancel_btn)
        self._generate_pair = GenerateWithHowMany(self._generate_btn, self._how_many)
        btn_row.addWidget(self._generate_pair)
        return btn_row

    def _build_sent_row(self) -> QWidget:
        row = QWidget()
        line = QHBoxLayout(row)
        line.setContentsMargins(0, 0, 0, 0)
        line.setSpacing(BUTTON_GAP)
        self._sent_note = QLabel()
        self._unsend_button = QPushButton(UNSEND_CAPTION)
        self._unsend_button.setIcon(qt_icon("cross"))
        self._unsend_button.clicked.connect(
            lambda _checked=False: self._on_unsend(self._offered_lane))
        line.addWidget(self._sent_note)
        line.addWidget(self._unsend_button)
        return row

    def minimumSizeHint(self):
        """Qt takes an explicit setMinimumWidth in place of this hint, not alongside it, so none is set here or on the wrapper."""
        hint = super().minimumSizeHint()
        hint.setWidth(min(self._contents_floor(), _FLOOR_CAP))
        return hint

    def _contents_floor(self) -> int:
        body = self._scroll.widget()
        return (body.minimumSizeHint().width()
                + self._scroll.verticalScrollBar().sizeHint().width()
                + 2 * self._scroll.frameWidth()
                + 2 * MARGIN_STANDARD)

    def _can_generate(self) -> bool:
        return (self._client is not None
                and workflow_named(self._workflow_dropdown.currentData()) is not None
                and self._why_generate_is_blocked() is None)

    def _sync_generate(self) -> None:
        self._generate_pair.setEnabled(self._can_generate())
        blocked = self._why_generate_is_blocked()
        if blocked:
            self._generate_btn.setToolTip(blocked)
        note = self._why_the_item_cannot_be_remade()
        set_marked_text(self._cannot_remake_note, wrappable(note or ""), mark="warning" if note else "",
                        color=YELLOW)
        self._cannot_remake_note.setVisible(note is not None)

    def _why_generate_is_blocked(self) -> str | None:
        workflow = workflow_named(self._workflow_dropdown.currentData())
        if workflow is not None and not workflow.generates_here:
            return MADE_ELSEWHERE_TIP
        lost = self._lost_workflow()
        if lost is not None:
            return _select_a_workflow_first(lost)
        models = list(self._models_not_installed().values())
        images = self._missing_inputs()
        return ((_pick_installed_ones_first(models) if models else None)
                or (_nothing_to_start_from(images) if images else None)
                or (ALREADY_MAKING_ONE_TIP if self._folder_is_making_one() else None))

    def _why_the_item_cannot_be_remade(self) -> str | None:
        lost = self._lost_workflow()
        if lost is not None:
            return _lost_workflow_note(lost)
        shown = self._displayed_row
        if shown is None or shown.get("workflow_name") != self._workflow_dropdown.currentData():
            return None
        models = list(self._models_not_installed().values())
        return _not_installed_note(models) if models else None

    def _lost_workflow(self) -> str | None:
        shown = self._displayed_row
        if shown is None or self._workflow_dropdown.currentData() is not None:
            return None
        workflow_name = shown.get("workflow_name") or ""
        return None if workflow_named(workflow_name) is not None else workflow_name

    def _models_not_installed(self) -> dict[str, str]:
        wf = workflow_named(self._form_workflow_key)
        if wf is None or self._param_form is None:
            return {}
        return not_installed(self._param_form.get_values(), self._param_form.definitions(),
                             (*wf.model_keys, *wf.lora_keys))

    def set_how_many(self, count: int) -> None:
        self._how_many.set_how_many(count)

    def set_making_one_check(self, is_making_one) -> None:
        self._making_one = is_making_one

    def reread_generate_button(self) -> None:
        self._sync_generate()
        self.refresh_generate_caption()

    def _folder_is_making_one(self) -> bool:
        return self._making_one is not None and self._making_one(self.current_config())

    def _missing_inputs(self) -> list[str]:
        wf = workflow_named(self._workflow_dropdown.currentData())
        if wf is None or self._param_form is None:
            return []
        return wf.missing_inputs(self._param_form.get_values())

    def _on_workflow_changed(self):
        self._forget_settings_source()
        self._end_folder_modify()
        self._fresh_form = False
        key = self._workflow_dropdown.currentData()
        wf = workflow_named(key)
        if wf is not None:
            self._offer_workflows(makes=wf.output_type, holding=key)
            edited = self._edited_form_values()
            deriver = wf.derived_display_size if wf.derives_size_from_input else None
            self._install_form(ParamForm(
                wf.param_definitions(),
                WorkflowTraits(size_deriver=deriver,
                               size_source=wf.derived_size_source,
                               hidden_keys=wf.enhance_keys(),
                               pins_reused_seed=wf.pins_reused_seed(),
                               lora_keys=wf.lora_keys),
                FormHelpers(heights=self._heights,
                            seed_history=SeedHistory(self._seed_uses, self._looping_preview),
                            items=self._zone_items())))
            self._form_workflow_key = key
            defaults = wf.default_params()
            carried_over = {
                k: v for k, v in edited.items()
                if k in defaults and v != defaults[k]
            }
            if carried_over:
                self._param_form.set_values(carried_over, carried=True)
                self._param_form.put_seeds(carried_over, is_random=False)
            checkpoint = self._param_form.get_values().get("checkpoint")
            if not self._loading_config:
                self._rebase_on_the_model(None, checkpoint, keep=edited)
                self._fresh_form = True
            self._form_checkpoint = checkpoint
            self.lora_offers.offer()
        else:
            self._clear_form()
        self._show_advice()
        self._refresh_estimate()
        self.refresh_generate_caption()
        self._sync_generate()
        self._emit_title()
        self.show_recent_preview()

    def _edited_form_values(self) -> dict:
        prior = workflow_named(self._form_workflow_key)
        if self._param_form is None or prior is None:
            return {}
        values = self._param_form.get_values()
        fresh = fresh_settings(prior.default_params(), values.get("checkpoint"))
        drawn = self._param_form.random_seed_keys()
        return {
            k: v for k, v in values.items()
            if k not in drawn and (k not in fresh or v != fresh[k])
        }

    def _follow_the_model(self):
        if self._param_form is None:
            return
        before = self._form_checkpoint
        self._form_checkpoint = self._param_form.get_values().get("checkpoint")
        if self._fresh_form and not self._loading_config and before != self._form_checkpoint:
            self._rebase_on_the_model(before, self._form_checkpoint)

    def _rebase_on_the_model(self, before, after, keep=()):
        defaults = workflow_named(self._form_workflow_key).default_params()
        old, new = fresh_settings(defaults, before), fresh_settings(defaults, after)
        following = {k: new[k] for k, v in self._param_form.get_values().items()
                     if k in old and k not in keep and v == old[k] != new[k]}
        with self._loading():
            self._param_form.set_values(following)

    def _show_advice(self):
        form = self._param_form
        if form is not None:
            values = form.get_values()
            definitions = form.definitions()
            workflow = workflow_named(self._form_workflow_key)
            lora_keys = workflow.lora_keys if workflow is not None else ()
            form.set_warnings({**trigger_word_advice(values, lora_keys,
                                                     in_scenes=form.tells_a_story()),
                               **setting_advice(values, definitions),
                               **self._file_advice(values, definitions, workflow)})
            form.show_readings(prompt_readings(self._form_workflow_key, values))
            form.mark_recommended(recommended_choices(values))
            form.explain(recommendations(values))
        self._workflow_warning.warn(form.every_warning() if form is not None else "")

    def _file_advice(self, values: dict, definitions, workflow) -> dict:
        if workflow is None:
            return {}
        defaults = workflow.default_params()
        return {**not_offered_advice(values, definitions,
                                     (*workflow.model_keys, *workflow.lora_keys), defaults,
                                     workflow.display_name),
                **not_installed_advice(self._models_not_installed(), definitions, defaults,
                                       in_scenes=self._param_form.tells_a_story())}

    def _resolve_every_warning(self):
        self._param_form.resolve_every_warning()

    def _detach_form(self):
        """Detached from its parent at once: Qt's deleteLater leaves it on screen until the event loop spins."""
        if self._param_form is None:
            return
        self._form_host_column.removeWidget(self._param_form)
        self._param_form.setParent(None)
        self._param_form.deleteLater()
        self._param_form = None

    def _clear_form(self):
        had_form = self._param_form is not None
        self._detach_form()
        self._form_workflow_key = None
        if had_form:
            self.prompt_fields_changed.emit()

    def _install_form(self, form: ParamForm):
        self._detach_form()
        self._param_form = form
        self._param_form.changed.connect(self.form_edited)
        self._param_form.text_fields_changed.connect(self.prompt_fields_changed)
        self._param_form.changed.connect(self._note_user_edit)
        self._param_form.changed.connect(self._follow_the_model)
        self._param_form.changed.connect(self._show_advice)
        self._param_form.changed.connect(self.refresh_modified_message)
        self._param_form.changed.connect(self._mark_prompt_edits)
        self._param_form.changed.connect(self.refresh_generate_caption)
        self._param_form.changed.connect(self._sync_generate)
        self._param_form.seed_drawn.connect(self._record_drawn_seed)
        self._param_form.item_activated.connect(self.link_clicked)
        if form.request_exchange() is not None:
            form.request_exchange().asked.connect(self._on_request_asked)
        self.lora_offers.form_replaced()
        self._form_host_column.addWidget(self._param_form)
        # Qt defers deleteLater, so the outgoing form is still alive here.
        self.prompt_fields_changed.emit()

    def lora_value(self, key: str):
        return self._param_form.get_values().get(key) if self._param_form is not None else None

    def pick_lora(self, key: str, lora: str) -> bool:
        wf = workflow_named(self._form_workflow_key)
        if self._param_form is None or wf is None or key not in wf.lora_keys:
            return False
        self._param_form.set_values({key: lora})
        return True

    def prompt_fields(self) -> list:
        return self._param_form.text_fields() if self._param_form is not None else []

    def _emit_title(self):
        self.title_changed.emit(self.title())

    def _refresh_estimate(self):
        wf = workflow_named(self._workflow_dropdown.currentData())
        self._estimate_label.setVisible(wf is not None and wf.generates_here)
        if wf is not None and wf.generates_here:
            self._estimate_label.setText(
                f"Typical time: {estimate_label(self._db.recent_durations(wf.name))}"
            )

    def refresh_generate_caption(self):
        self._caption_timer.start()

    def _apply_generate_caption(self):
        self._generate_pair.offer_how_many(self._folder_modify is None)
        if self._folder_modify is not None:
            self._generate_btn.set_caption(self._folder_modify.caption())
            self._generate_btn.setToolTip(self._folder_modify.tooltip())
            return
        wf = workflow_named(self._workflow_dropdown.currentData())
        config = self.current_config()
        duplicate = (
            wf is not None and self._can_generate()
            and (self._would_remake_what_it_shows()
                 or (config.seed_is_random
                     and self._shown_run_the_form_still_holds() is not None)
                 or would_reproduce_a_completed_run(
                     self._library.now().rows, wf, config.params,
                     seed_is_random=config.seed_is_random,
                 ))
        )
        self._generate_btn.set_caption(
            RANDOM_SEED_CAPTION if duplicate else DEFAULT_CAPTION)
        self._generate_btn.setToolTip(
            self._why_generate_is_blocked() or (_RANDOM_SEED_TIP if duplicate else ""))

    def _on_generate(self):
        if not self._can_generate() or refused_over_prompts(
                self._generate_btn, self.prompt_fields(), self._param_form.remove_unread_emphasis):
            return
        key = self._workflow_dropdown.currentData()
        if self._folder_modify is not None:
            if self._folder_modify.is_unchanged(self.current_config()):
                self._generate_btn.flash_guard(_MODIFY_GUARD)
                return
            self.modify_requested.emit(self._folder_modify.folder_key, key,
                                       self._param_form.get_values())
            return
        if self._would_remake_what_it_shows():
            self.use_random_seed()
        self.generate_requested.emit(key, self._batch_of(self._how_many.how_many()))
        self._param_form.roll_random_seeds()

    def _batch_of(self, how_many: int) -> list[dict]:
        batch = [self._param_form.get_values()]
        while len(batch) < how_many:
            if self._param_form.random_seed_keys():
                self._param_form.roll_random_seeds()
            else:
                self.use_random_seed()
            batch.append(self._param_form.get_values())
        return batch

    def set_settings_source(self, category: str, video_prompt_id: str | None,
                            intent: str) -> None:
        self._settings_source = (category or "", video_prompt_id or None, intent)
        self._source_video_row = self._db.get_generation(video_prompt_id) if video_prompt_id else None
        self._related.show_row(self._the_row_generate_would_make(), self._image_rows())

    def _the_row_generate_would_make(self) -> dict:
        return {"workflow_name": self._workflow_dropdown.currentData(),
                "params_json": json.dumps(self._param_form.get_values()),
                "source_video": self._settings_source[1]}

    def settings_source(self) -> tuple[str, str | None, str]:
        return self._settings_source

    def _prompts_differ_from_source(self) -> bool:
        workflow = workflow_named(self._workflow_dropdown.currentData())
        return (self._source_video_row is not None and workflow is not None
                and self._param_form is not None
                and prompts_differ_from(self._param_form.get_values(),
                                        self._source_video_row, workflow))

    def _forget_settings_source(self) -> None:
        self._settings_source = ("", None, "")
        self._source_video_row = None

    def _mark_prompt_edits(self) -> None:
        if self._live_source is None:
            self._viewport.mark_prompt_edited(self._prompts_differ_from_source())

    def show_combination(self, combination: Combination) -> None:
        if self._live_source is None:
            combination = combination._replace(
                prompt_edited=self._prompts_differ_from_source())
        self._viewport.show_combination(combination)
        self._reflow_for_the_media()

    def launched_runs(self) -> list[str]:
        return list(self._launched_runs)

    def note_launched(self, origin: str, made_of: dict | None = None):
        self._launched_runs[origin] = made_of
        if made_of is not None:
            self._mark_prompts()

    def forget_launched(self, origins=None):
        ended = [self._launched_runs.pop(origin) for origin in self.launched_runs()
                 if origins is None or origin in origins]
        if any(made_of is not None for made_of in ended):
            self._mark_prompts()

    def set_generating(self, generating: bool, *, auto_generating: bool = False):
        self._cancel_btn.setToolTip(cancel_tooltip(auto_generating))
        if generating == self._generating:
            return
        self._generating = generating
        self._cancel_btn.setVisible(generating)

    def use_random_seed(self):
        if self._param_form is not None:
            with self._loading():
                self._param_form.set_seed_random(True)

    def _set_displayed_row(self, row: dict | None) -> None:
        self._displayed_row = row
        if self._param_form is not None:
            self._param_form.show_item(merge_denormalized(row) if row is not None else {},
                                       (row or {}).get("thumbnail_path"))

    def _seed_uses(self, key: str) -> list[SeedUse]:
        return seed_history(self._db.seed_history_rows(), key, self._db.list_seed_uses(),
                            makes=self._makes())

    def _looping_preview(self, item: str) -> str | None:
        row = self._db.get_generation(item)
        return self._animated_preview(row) if row else None

    def _zone_items(self) -> ZoneItems:
        return ZoneItems(
            self._db, self._names, self._library,
            ZoneFolders(places=OUTPUT_PLACES, input_dir=COMFYUI_INPUT_DIR, thumb_dir=THUMB_DIR),
            moving_preview=self._animated_preview)

    def _record_drawn_seed(self, key: str, seed: int) -> None:
        width, height = self._param_form.output_size() or (None, None)
        self._db.record_seed_use(NewSeedUse(kind=SeedUseKind.DRAWN, seed_key=key, seed=seed,
                                 media_type=self._makes(), width=width, height=height))

    def _makes(self) -> MediaType | None:
        return workflow_output_type(self._workflow_dropdown.currentData())

    def _image_rows(self):
        return self._library.now().image_rows

    def workflow_and_signature(self, image_index: dict | None = None,
                               ) -> tuple[str, str] | None:
        key = self._workflow_dropdown.currentData()
        wf = workflow_named(key)
        if wf is None or self._param_form is None:
            return None
        params_json = json.dumps(self._param_form.get_values())
        if image_index is None:
            image_index = self._library.now().image_config_index
        shown = self._shown_run_the_form_still_holds(params_json, image_index) or {}
        return key, settings_signature(key, params_json, image_index,
                                       workflow_version=shown.get("workflow_version"))

    def _shown_run_the_form_still_holds(self, params_json: str | None = None,
                                       image_index: dict | None = None) -> dict | None:
        row = self._displayed_row
        workflow_name = self._workflow_dropdown.currentData()
        if row is None or self._param_form is None or not workflow_name:
            return None
        if (row.get("workflow_name") or "") != workflow_name:
            return None
        if params_json is None:
            params_json = json.dumps(self._param_form.get_values())
        if image_index is None:
            image_index = self._library.now().image_config_index
        holds_it = (settings_signature(workflow_name, params_json, image_index)
                    == settings_signature(workflow_name, row.get("params_json"), image_index))
        return row if holds_it else None

    def settings_folder_key(self) -> str | None:
        key = self.workflow_and_signature()
        if key is None or self._recent_matching_row() is None:
            return None
        return config_folder_key(*key)

    def refresh_media_layout(self) -> None:
        self._reflow_for_the_media()

    def become_hosted(self, session) -> None:
        self._fun_time = session
        self._reflow_for_the_media()

    def become_standalone(self) -> None:
        self._fun_time = None
        self._stand_the_media(beside=False)

    def _reflow_for_the_media(self) -> None:
        if self._fun_time is None:
            return
        self._stand_the_media(beside=self._media_is_portrait())

    def _stand_the_media(self, *, beside: bool) -> None:
        if beside == self._media_side_by_side:
            return
        self._media_side_by_side = beside
        sizes = self._media_split.sizes()
        if beside:
            self._media_split.setOrientation(Qt.Orientation.Horizontal)
            self._media_split.insertWidget(0, self._settings_pane)
        else:
            self._media_split.setOrientation(Qt.Orientation.Vertical)
            self._media_split.insertWidget(0, self._viewport_pane)
        self._media_split.setStretchFactor(0, 3 if beside else 0)
        self._media_split.setStretchFactor(1, 4 if beside else 0)
        if sum(sizes) > 0:
            self._media_split.setSizes(sorted(sizes, reverse=True))

    def _media_is_portrait(self) -> bool:
        size = self._viewport.media_size()
        return bool(size) and shape_of_size(*size) == PORTRAIT

    def show_recent_preview(self):
        if self._autoshow_held:
            return
        row = self._recent_matching_row()
        if row is not None and resolve_preview(row, OUTPUT_PLACES) is not None:
            self._display_result(row, self._image_rows())
            return
        self._viewport.clear()
        self._set_displayed_row(None)
        self._hide_footer()
        self._arm_preview_actions()
        self._note_displayed_config()
        self._emit_title()

    def _recent_matching_row(self) -> dict | None:
        library = self._library.now()
        matching = library.in_settings(self.workflow_and_signature(library.image_config_index))
        return matching[0] if matching else None

    def current_config(self) -> ConfigSnapshot:
        if self._param_form is None:
            return ConfigSnapshot(self._workflow_dropdown.currentData(), {}, False)
        return ConfigSnapshot(
            self._workflow_dropdown.currentData(),
            self._param_form.get_values(),
            self._param_form.seed_is_random(),
        )

    def is_blank(self) -> bool:
        return self._workflow_dropdown.currentData() is None and self._displayed_row is None

    def title(self) -> str:
        if self._folder_modify is not None:
            return self._folder_modify.title()
        return self.name() or "New generation"

    def name(self) -> str:
        if self._folder_modify is not None:
            return self._folder_modify.label
        name = self._item_name()
        if not name:
            key = self.workflow_and_signature()
            if key is not None:
                name = config_folder_name(*key, self._db.folder_meta_map())
        return name

    def _item_name(self) -> str:
        return self._names.of((self._displayed_row or {}).get("prompt_id"))

    def reread_name(self) -> None:
        if self._displayed_row is not None:
            self._basic_section.setVisible(self._basic_section.show_name(self._item_name()))
        for zone in self.reaches():
            zone.reread_name()

    def reaches(self) -> tuple[DropZone, ...]:
        return () if self._param_form is None else self._param_form.drop_zones()

    def tab_icon(self) -> QIcon:
        row = self._displayed_row
        thumb = (row or {}).get("thumbnail_path")
        if thumb and Path(thumb).exists():
            return QIcon(QPixmap(str(thumb)))
        media = media_type_of_row(row) if row is not None else self._makes()
        return icons.media_type_icon(media) if media else QIcon()

    def prefill(self, workflow_name: str, params: dict):
        with self._loading():
            self._fresh_form = False
            self._end_folder_modify()
            self._forget_watch()
            workflow = workflow_named(workflow_name)
            if workflow is not None:
                self._offer_workflows(makes=workflow.output_type, holding=workflow_name)
                self._workflow_dropdown.setCurrentIndex(self._workflow_dropdown.findData(workflow_name))
            if self._param_form:
                self._param_form.clear_prompt_rewrites()
                self._param_form.replace_values(params)
            self.show_recent_preview()

    def _offer_workflows(self, *, makes: MediaType | None, holding: str | None) -> None:
        dropdown = self._workflow_dropdown
        current = dropdown.currentData()
        listed = [workflow.name for workflow in offered_workflows(makes=makes)]
        if holding is not None and holding not in listed:
            listed.append(holding)
        if listed == [dropdown.itemData(index) for index in range(dropdown.count())]:
            return
        blocked = dropdown.blockSignals(True)
        try:
            dropdown.clear()
            for name in listed:
                dropdown.addItem(workflow_named(name).display_name, name)
            dropdown.setCurrentIndex(dropdown.findData(current) if current is not None else -1)
        finally:
            dropdown.blockSignals(blocked)

    def restore_config(self, snapshot: ConfigSnapshot):
        with self._loading():
            self.prefill(snapshot.workflow_name, snapshot.params)
            if self._param_form:
                self._param_form.set_seed_random(snapshot.seed_is_random)
                self._param_form.put_seeds(snapshot.params, is_random=snapshot.seed_is_random)

    def saved_layout(self) -> dict:
        if self._fun_time is None:
            self._media_border = self._media_split.dragged_sizes() or self._media_border
        return {"folds": self._param_form.folds() if self._param_form else {},
                "enhancement_levels_folded": self._versions.is_collapsed(),
                "details_folded": self._basic_section.is_folded(),
                "related_folds": self._related.folds(),
                "media_border": self._media_border}

    def restore_layout(self, saved) -> None:
        if not isinstance(saved, dict):
            return
        folds = saved.get("folds")
        if self._param_form and isinstance(folds, dict):
            self._param_form.set_folds(folds)
        if isinstance(saved.get("enhancement_levels_folded"), bool):
            self._versions.set_collapsed(saved["enhancement_levels_folded"])
        if isinstance(saved.get("details_folded"), bool):
            self._basic_section.set_folded(saved["details_folded"])
        if isinstance(saved.get("related_folds"), dict):
            self._related.set_folds(saved["related_folds"])
        self._media_border = saved.get("media_border", saved.get("picture_border"))
        if self._fun_time is None:
            self._media_split.take_dragged_sizes(self._media_border)

    def open_folder_modify(self, folder_key: str, label: str, workflow_name: str,
                      params: dict, thumbnails: list) -> None:
        self.prefill(workflow_name, params)
        self._folder_modify = FolderModify(
            folder_key=folder_key, label=label, count=len(thumbnails),
            opened_on=self.current_config(),
        )
        self._hide_footer()
        self._set_displayed_row(None)
        self._displayed_config = None
        self._viewport.show_folder(thumbnails)
        self._reflow_for_the_media()
        self._mark_prompts()
        self._apply_generate_caption()
        self._emit_title()

    def _end_folder_modify(self) -> None:
        if self._folder_modify is None:
            return
        self._folder_modify = None
        self._mark_prompts()
        self._apply_generate_caption()

    def show_saved_generation(self, row: dict, image_rows: list[dict]):
        self._point_elsewhere(row)
        self._display_result(row, image_rows)

    def show_running_generation(self, row: dict):
        self._point_elsewhere(row)
        self._hide_footer()
        self._related.show_requests_and_modifications(row["prompt_id"])
        self._viewport.clear()
        self._note_displayed_config(being_made=row)
        self._emit_title()

    def _point_elsewhere(self, row: dict):
        self.forget_launched()
        self._forget_watch()
        self._forget_settings_source()
        self._set_displayed_row(None)
        self._end_folder_modify()
        workflow_name = row.get("workflow_name", "")
        self._autoshow_held = True
        try:
            if workflow_named(workflow_name) is not None:
                self.prefill(workflow_name, merge_denormalized(row))
            else:
                with self._loading():
                    self._workflow_dropdown.setCurrentIndex(-1)
                    self._offer_workflows(makes=media_type_of_row(row), holding=None)
        finally:
            self._autoshow_held = False

    def show_completed_result(self, row: dict, image_rows: list[dict]):
        if self._folder_modify is not None:
            return
        self._display_result(row, image_rows, made_with=merge_denormalized(row))

    def refresh_displayed(self, row: dict, image_rows: list[dict]):
        shown = self._displayed_row
        if shown is None or shown.get("prompt_id") != row.get("prompt_id"):
            return
        self._display_result(row, image_rows)

    def show_finished_media(self, row: dict):
        preview = resolve_preview(row, OUTPUT_PLACES)
        if preview is None:
            return
        self._live_note = None
        self._viewport.show_media(*preview, row["prompt_id"])
        self._arm_preview_actions(row["prompt_id"])

    def watched_key(self) -> str | None:
        return self._watched_key

    def watch_folder(self, key: str, frame: bytes | None, note: str | None = None,
                     made_from: Combination | None = None):
        self._watched_key = key
        self._live_note = None
        if frame:
            self.show_live_frame(frame)
        elif made_from is not None and (made_from.image or made_from.source_video):
            self.show_live_source(made_from)
        else:
            self.show_live_wait(note)

    def show_live_source(self, made_from: Combination):
        if made_from == self._live_source:
            return
        self._live_source = made_from
        self.show_combination(made_from)

    def show_live_frame(self, frame: bytes):
        self._live_note = None
        self._live_source = None
        self._viewport.show_frame(frame)

    def show_live_wait(self, note: str | None):
        text = note or _WAITING_NOTE
        if text == self._live_note:
            return
        self._live_note = text
        self._live_source = None
        self._viewport.show_message(text, live=True)

    def is_awaiting_frame(self) -> bool:
        return self._watched_key is not None and self._live_note is not None

    def stop_watching(self):
        if self._watched_key is None:
            return
        self._forget_watch()
        if self._displayed_row is not None:
            self._restore_preview()
        elif self._workflow_dropdown.currentData() is not None:
            self.show_recent_preview()
        else:
            self._viewport.clear()

    def _forget_watch(self):
        self._watched_key = None
        self._live_note = None
        self._live_source = None

    def _display_result(self, row: dict, image_rows: list[dict],
                        made_with: dict | None = None):
        arriving = (self._displayed_row is None
                    or self._displayed_row.get("prompt_id") != row.get("prompt_id"))
        self._set_displayed_row(row)
        preview = resolve_preview(row, OUTPUT_PLACES)
        if preview is not None:
            self._viewport.show_media(*preview, row["prompt_id"])
        else:
            self._viewport.clear()
        self._show_footer(row, image_rows, preview)
        self._arm_preview_actions()
        if arriving:
            self._note_displayed_config(made_with)
        else:
            self.refresh_modified_message()
        self._sync_generate()
        self._emit_title()
        self.displayed_changed.emit()

    def _arm_preview_actions(self, prompt_id: str | None = None):
        if prompt_id is None and self._displayed_row is not None:
            prompt_id = self._displayed_row["prompt_id"]
        row = self._db.get_generation(prompt_id) if prompt_id is not None else None
        if row is None:
            self._viewport.set_actions(None)
            return
        self._viewport.set_actions(
            row["prompt_id"], favorite=bool(row.get("starred")),
            enhance=enhance_state(row, self._enhance_settings),
        )

    def reconcile_preview(self, live_ids):
        shown = self._displayed_row
        if shown is not None and shown.get("prompt_id") not in live_ids:
            self._viewport.clear()
        self._reread_corners()

    def _reread_corners(self):
        armed = self._viewport.actions_id()
        if armed is not None:
            self._arm_preview_actions(armed)

    def _note_displayed_config(self, made_with: dict | None = None, *,
                               being_made: dict | None = None):
        self._displayed_config = (
            self._item_config(made_with) if self._displayed_row is not None else None
        )
        if self._param_form is not None:
            self._aim_the_request(self._displayed_row or being_made)
            self._mark_prompts()
        self.refresh_modified_message()

    def _mark_prompts(self) -> None:
        if self._param_form is None:
            return
        marked_against = self._marked_against()
        with self._loading():
            if marked_against is None:
                self._param_form.clear_prompt_rewrites()
            else:
                self._param_form.track_prompt_rewrites(marked_against)

    def _marked_against(self) -> dict | None:
        if pressed := [made_of for made_of in self._launched_runs.values() if made_of is not None]:
            return pressed[-1]
        if self._folder_modify is not None:
            return self._folder_modify.opened_on.params
        return None if self._displayed_config is None else self._settings_shown().params

    def _settings_shown(self) -> ConfigSnapshot:
        return self._displayed_config or self._item_config()

    def _aim_the_request(self, row: dict | None) -> None:
        exchange = self._param_form.request_exchange()
        if exchange is None:
            self._request_aim = None
            return
        if row is None:
            self._request_aim = None
            exchange.set_available(False)
            return
        params = self._settings_shown().params
        self._request_aim = _RequestAim(
            prompt_id=row["prompt_id"],
            shown=(params.get("positive_prompt") or "", params.get("negative_prompt") or ""))
        exchange.set_available(self._displayed_config is not None)
        exchange.show_exchange(self._db.requests.exchange_of(row["prompt_id"]))

    def asked(self) -> dict | None:
        aim = self._request_aim
        if aim is None or not aim.turns:
            return None
        return {"asked": aim.turns[-1].said, "source_prompt_id": aim.prompt_id,
                "old_positive": aim.shown[0], "old_negative": aim.shown[1],
                "turns": list(aim.turns)}

    def _on_request_asked(self, words: str) -> None:
        aim = self._request_aim
        if aim is None or not words:
            return
        self._asked += 1
        self._param_form.request_exchange().add_turn(words)
        params = self.current_config().params
        self._requests.ask(
            aim.prompt_id, (params.get("positive_prompt") or "", params.get("negative_prompt") or ""),
            words, settings=request_settings.settings_to_tell(self._param_form.definitions(), params),
            in_scenes=self._param_form.tells_a_story(),
            owner=self,
            then=lambda revision, context=(self._asked, aim.prompt_id): self._on_rewritten(
                context, revision))

    def _on_rewritten(self, context, revision) -> None:
        asked, prompt_id = context
        aim = self._request_aim
        if asked != self._asked or aim is None or aim.prompt_id != prompt_id:
            return
        exchange = self._param_form.request_exchange()
        if revision is None:
            exchange.failed()
            return
        if revision.settings:
            self._param_form.set_values({**self._param_form.get_values(), **dict(revision.settings)})
        if revision.changed:
            self._param_form.set_prompts(revision.positive, revision.negative, typed=True)
        turn = revision.turn(exchange.turns()[-1][0])
        aim.turns.append(turn)
        exchange.answered(turn)

    def _item_config(self, made_with: dict | None = None) -> ConfigSnapshot:
        current = self.current_config()
        if self._param_form is None:
            return current
        params = {key: (made_with or {}).get(key, value)
                  for key, value in current.params.items()}
        return ConfigSnapshot(current.workflow_name,
                              {**params, **self._param_form.item_seeds()},
                              seed_is_random=False)

    def refresh_modified_message(self):
        modified = (self._displayed_config is not None
                    and not self._would_remake_what_it_shows())
        self._viewport.set_message(_MODIFIED_MESSAGE if modified else None)

    def _would_remake_what_it_shows(self) -> bool:
        return (self._displayed_config is not None
                and configs_match(self._displayed_config, self.current_config()))

    def _hide_footer(self):
        self._basic_section.hide()
        self._action.clear()
        self._related.clear()
        self._versions.hide()
        self._pending_enhancement = None
        self._update_lane_button(None)

    def _show_footer(self, row: dict, image_rows: list[dict], preview):
        self.reread_folder_buttons()
        self._basic_section.setVisible(
            self._basic_section.show_row(row, self._upscale_of(row), self._item_name()))
        self._action.show_row(row)
        self._related.show_row(row, image_rows)
        self._refresh_versions()
        self._update_lane_button(preview)

    def displayed_row(self) -> dict | None:
        return self._displayed_row

    def set_pending_enhancement(self, pending: RunningEnhancement | None):
        if pending == self._pending_enhancement:
            return
        was_running = self._pending_enhancement is not None
        self._pending_enhancement = pending
        if pending is not None:
            frame = pending.frame
            if frame:
                self._viewport.show_frame(frame, enhancing=True)
        elif was_running:
            self._restore_preview()
        if self._versions.update_pending(pending):
            return
        self._refresh_versions()

    def _restore_preview(self):
        row = self._displayed_row
        preview = resolve_preview(row, OUTPUT_PLACES) if row else None
        if preview is None:
            self._viewport.clear()
            return
        self._viewport.show_media(*preview, row["prompt_id"])
        self._arm_preview_actions()
        self.refresh_modified_message()

    def set_fullscreen_factory(self, make):
        self._viewport.set_fullscreen_factory(make)

    def open_slideshow(self):
        return self._viewport.open_fullscreen()

    def set_enhance_settings(self, settings: EnhanceSettings):
        if settings == self._enhance_settings:
            return
        self._enhance_settings = settings
        self._refresh_versions()
        self._reread_corners()

    def _on_enhance_requested(self):
        if self._displayed_row is not None:
            self.enhance_requested.emit(self._displayed_row["prompt_id"])

    def _on_go_to_folder(self):
        if self._displayed_row is not None:
            self.go_to_folder_requested.emit(self._displayed_row["prompt_id"])

    def set_folder_check(self, can_go) -> None:
        self._can_go_to_folder = can_go

    def reread_folder_buttons(self) -> None:
        row, can_go = self._displayed_row, self._can_go_to_folder
        self._go_to_folder.setVisible(
            row is not None and can_go is not None and can_go(row))
        if row is not None:
            self._basic_section.setVisible(self._basic_section.has_content())

    def _on_versions_delete_requested(self, positions: list):
        row = self._displayed_row
        if row is None:
            return
        versions = self._listed_versions
        names = [versions[p].file.get("filename") for p in positions
                 if 0 <= p < len(versions)]
        if names:
            self.versions_delete_requested.emit(row["prompt_id"], names)

    def _refresh_versions(self):
        row = self._displayed_row
        if row is None:
            self._listed_versions = []
            self._versions.show_versions([])
            return
        if media_type_of_row(row) != MediaType.IMAGE:
            self._listed_versions = displayed_versions(row, self._upscale_of(row))
            self._versions.show_versions(
                [(version, row.get("thumbnail_path")) for version in self._listed_versions],
                dating=Dating(str(row.get("created_at", "")), row.get("days_in_trash")),
                deletable=False,
            )
            return
        self._listed_versions = displayed_versions(row)
        self._versions.show_versions(
            [(version, self._version_path(version)) for version in self._listed_versions],
            self._pending_enhancement, self._add_row_for(row),
            Dating(str(row.get("created_at", "")), row.get("days_in_trash")),
        )

    def _upscale_of(self, row: dict) -> Path | None:
        if media_type_of_row(row) != MediaType.VIDEO:
            return None
        preview = resolve_preview(row, OUTPUT_PLACES)
        if preview is None:
            return None
        return self._library.now().upscales.upscale_of(preview[0])

    def _add_row_for(self, row: dict) -> EnhanceOffer:
        params = enhance_params_for(row, self._enhance_settings)
        return EnhanceOffer(describe_enhance_params(params or {}),
                            version_matching_settings(row, self._enhance_settings))

    @staticmethod
    def _version_path(version) -> Path:
        return output_file_path(version.file, OUTPUT_PLACES)

    def _show_version(self, position: int):
        if self._displayed_row is None or not 0 <= position < len(self._listed_versions):
            return
        path = self._version_path(self._listed_versions[position])
        if path.exists():
            self._viewport.show_media(path, media_type_of_row(self._displayed_row),
                                     self._displayed_row["prompt_id"])
            self._arm_preview_actions()
            self.refresh_modified_message()

    def _video_rows(self) -> list[dict]:
        return self._library.now().video_rows

    def _update_lane_button(self, preview):
        row = self._displayed_row or {}
        is_video = preview is not None and preview[1] == MediaType.VIDEO and made_here(row)
        lane = self._offered_lane = lane_for(row) if is_video else None
        sent = is_video and bool(row.get(lane.flag))
        self._lane_button.setVisible(is_video and not sent)
        self._sent_row.setVisible(sent)
        if not is_video:
            return
        self._lane_button.setText(lane.send_caption)
        self._lane_button.setToolTip(
            lane.withdrawn_tooltip if row.get(lane.unsent_flag) else lane.tooltip)
        self._sent_note.setText(icon_then_text("check", lane.sent_caption, color=TEXT_PRIMARY,
                                               size=self._sent_note.fontMetrics().height()))
        self._unsend_button.setToolTip(lane.unsend_tooltip)

    def _on_send(self, lane):
        if not self._displayed_row or self._displayed_row.get(lane.flag):
            return
        path = self._displayed_video_path()
        if path is None:
            return
        try:
            lane.send(path, self._displayed_row["prompt_id"], db=self._db,
                      inbox=self._inbox, places=OUTPUT_PLACES)
        except Exception as e:
            logger.exception("Failed to send %s to %s", path, lane.name)
            QMessageBox.warning(self._viewport, lane.failure_title,
                                lane.failure_body(e))
            return
        self._redraw_lane_button()

    def _on_unsend(self, lane):
        if not self._displayed_row or not self._displayed_row.get(lane.flag):
            return
        lane.unmark(self._db, self._displayed_row["prompt_id"])
        self._redraw_lane_button()

    def _redraw_lane_button(self):
        prompt_id = self._displayed_row["prompt_id"]
        self._set_displayed_row(self._db.get_generation(prompt_id) or self._displayed_row)
        path = self._displayed_video_path()
        self._update_lane_button(None if path is None else (path, MediaType.VIDEO))

    def _displayed_video_path(self) -> Path | None:
        if not self._displayed_row:
            return None
        preview = resolve_preview(self._displayed_row, OUTPUT_PLACES)
        if preview is None or preview[1] != MediaType.VIDEO:
            return None
        return preview[0]

    def release_media(self, paths) -> None:
        self._viewport.release_media(paths)

    def osr2_drive_target(self):
        return drive_target_for(self._displayed_video_path(), self._viewport.player())

    def video_on_screen(self) -> str | None:
        return self._viewport.video_on_screen()

from __future__ import annotations

from datetime import datetime

import pytest
from PyQt6.QtCore import QEvent, QObject, QPoint, QPointF, QRect, Qt
from PyQt6.QtGui import QColor, QDropEvent, QFocusEvent, QImage
from PyQt6.QtWidgets import (
    QAbstractSlider,
    QApplication,
    QFormLayout,
    QLabel,
    QPushButton,
    QStyleOptionViewItem,
    QWidget,
)
from shared_ui.colors import BORDER_DEFAULT, TEXT_MUTED, TEXT_PRIMARY
from shared_ui.fonts import FONT_UI, SIZE_HEADING, make_font
from shared_ui.icons import qt_icon
from shared_ui.spacing import BUTTON_ICON
from shared_ui.tick_control import TickControl

import origenerator.gui.param_form as pf
from origenerator.box_breaks import BOX_BREAK
from origenerator.gallery.shapes import LANDSCAPE, PORTRAIT
from origenerator.gui import (
    diff_text,
    file_pick,
    icons,
    param_sections,
    thumbnail_dropdown,
    training_controls,
)
from origenerator.gui.collapsible_section import CollapsibleSection
from origenerator.gui.drop_zone import DropZone
from origenerator.gui.eliding import ElidingLabel
from origenerator.gui.generation_drag import generation_mime
from origenerator.gui.param_form import (
    BOTH_STRENGTHS_ONE_HELP,
    EVERY_SCENE_SPEAKS_HELP,
    STRENGTH_ONE_HELP,
    ParamForm,
)
from origenerator.gui.param_help import definition_help, option_help, param_help
from origenerator.gui.preset_dropdown import PresetDropdown
from origenerator.gui.prompt_boxes import PromptBoxes
from origenerator.gui.prompt_field import PromptField
from origenerator.gui.prompt_marks import RESOLVE_UNPAIRED_PARENTHESES, problem_to_resolve
from origenerator.gui.scenes_editor import SPEAKING_HELP, SPEAKING_NOTE
from origenerator.gui.stylesheet import build_stylesheet
from origenerator.gui.tooltip_shape import shaped
from origenerator.lora_training import TrainingOffer
from origenerator.prompt_tokens import CUT_OFF, READ_IN_PIECES
from origenerator.seed_history import SeedHistory, SeedUse
from origenerator.setting_advice import Advice, MissingTriggerWords, setting_advice
from origenerator.speech import CUSTOM_VOICE, VOICE_OPTIONS
from origenerator.workflows import WORKFLOW_REGISTRY
from origenerator.workflows.base import ParamDef, ParamType, story_of
from origenerator.workflows.lora_rows import strength_key_of
from origenerator.workflows.model_files import NO_LORA
from tests.text_readers import word_reading
from tests.thumbnail_rows import painted_row, square


def _section_titles(form) -> list[str]:
    layout = form.layout()
    widgets = (layout.itemAt(i).widget() for i in range(layout.count()))
    return [w._title for w in widgets if isinstance(w, CollapsibleSection)]


def test_a_form_with_a_prompt_has_a_request_section_right_after_its_prompts(qtbot):
    form = ParamForm(WORKFLOW_REGISTRY["sdxl_t2i"].param_definitions())
    qtbot.addWidget(form)

    titles = _section_titles(form)
    assert titles[titles.index("Prompts") + 1] == "Request"
    assert form.request_field() is not None


def test_a_form_with_no_prompt_has_no_request_to_make(qtbot):
    form = ParamForm([ParamDef("seed", "Seed", "seed", 0)])
    qtbot.addWidget(form)

    assert "Request" not in _section_titles(form)
    assert form.request_field() is None


def test_prompts_a_request_rewrites_show_their_whole_change_at_once(qtbot):
    form = ParamForm(WORKFLOW_REGISTRY["sdxl_t2i"].param_definitions())
    qtbot.addWidget(form)
    form.track_prompt_rewrites({"positive_prompt": "a cat on a couch", "negative_prompt": ""})

    form.set_prompts("a dog on a couch", "")

    (field,) = form._widgets["positive_prompt"].boxes()
    assert diff_text.live_text(field) == "a dog on a couch"
    assert "cat" in field.toPlainText()


def test_field_labels_fit_the_heading_font(qtbot):
    label_text = "LoRA Strength (High)"
    form = ParamForm([
        ParamDef("lora_strength_high", label_text, "float", 1.0,
                 min_val=0.0, max_val=2.0, step=0.05),
    ])
    form.setFont(make_font(FONT_UI, SIZE_HEADING))
    qtbot.addWidget(form)
    form._sections["Models & LoRAs"].set_collapsed(False)
    with qtbot.waitExposed(form):
        form.show()
    form.resize(600, form.height())
    form.layout().activate()

    label = next(w for w in form.findChildren(QLabel) if w.text() == label_text)
    assert label.isVisible()
    assert label.width() >= label.fontMetrics().horizontalAdvance(label_text)


def test_browse_button_fits_its_caption(qtbot):
    form = ParamForm([ParamDef("voice_sample", "Voice Sample", "audio", "")])
    form.setStyleSheet(build_stylesheet())
    form.setFont(make_font(FONT_UI, SIZE_HEADING))
    qtbot.addWidget(form)
    form.resize(800, 200)
    with qtbot.waitExposed(form):
        form.show()

    gauge = QWidget()
    gauge.setStyleSheet(build_stylesheet())
    gauge.setFont(make_font(FONT_UI, SIZE_HEADING))
    reference = QPushButton("Browse...", gauge)
    qtbot.addWidget(gauge)
    with qtbot.waitExposed(gauge):
        gauge.show()

    btn = form._browse_buttons["voice_sample"]
    assert btn.width() >= reference.sizeHint().width()


def test_bool_param_renders_a_tick_control_and_round_trips(qtbot):
    form = ParamForm([ParamDef("enhance", "Enhance", "bool", True)])
    qtbot.addWidget(form)
    assert isinstance(form._widgets["enhance"], TickControl)
    assert form.get_values()["enhance"] is True

    changes = []
    form.changed.connect(lambda: changes.append(1))
    form.set_values({"enhance": False})
    assert form.get_values()["enhance"] is False
    assert changes

    form.set_values({"enhance": True})
    assert form.get_values()["enhance"] is True


def test_seed_random_control_is_the_ticked_control(qtbot):
    form = ParamForm([ParamDef("seed", "Seed", "seed", 0)])
    qtbot.addWidget(form)
    assert isinstance(form._randomize_checks["seed"], TickControl)


def test_seed_field_has_a_copy_button_that_copies_its_value(qtbot):
    QApplication.clipboard().clear()
    form = ParamForm([ParamDef("seed", "Seed", "seed", 0)])
    qtbot.addWidget(form)
    form.set_values({"seed": 12345})

    form._copy_buttons["seed"].click()

    assert QApplication.clipboard().text() == "12345"


def test_prompt_copy_button_reads_the_live_edited_text(qtbot):
    QApplication.clipboard().clear()
    form = ParamForm([
        ParamDef("positive_prompt", "Positive Prompt", "str", "", multiline=True),
    ])
    qtbot.addWidget(form)
    form._widgets["positive_prompt"].boxes()[0].setPlainText("a red fox in snow")

    form._copy_buttons["positive_prompt"].click()

    assert QApplication.clipboard().text() == "a red fox in snow"


def test_prompt_fields_are_draggable_and_filed_under_their_param(qtbot):
    form = ParamForm([
        ParamDef("positive_prompt", "Positive Prompt", "str", "", multiline=True),
        ParamDef("name", "Name", "str", ""),
    ])
    qtbot.addWidget(form)
    (box,) = form._widgets["positive_prompt"].boxes()
    assert isinstance(box, PromptField)
    assert box._key == "positive_prompt"
    assert not isinstance(form._widgets["name"], PromptBoxes)
    assert form.text_fields() == [box]


def test_plain_scalar_and_single_line_fields_get_no_copy_button(qtbot):
    form = ParamForm([
        ParamDef("steps", "Steps", "int", 20),
        ParamDef("cfg", "CFG", "float", 7.0),
        ParamDef("name", "Name", "str", ""),
        ParamDef("input_image", "Input Image", "image", ""),
    ])
    qtbot.addWidget(form)
    assert form._copy_buttons == {}


def test_seed_keeps_its_random_tick_beside_the_copy_button(qtbot):
    form = ParamForm([ParamDef("seed", "Seed", "seed", 0)])
    qtbot.addWidget(form)
    assert "seed" in form._randomize_checks
    assert "seed" in form._copy_buttons


def test_a_written_seed_pins_itself_by_default(qtbot):
    form = ParamForm([ParamDef("seed", "Seed", "seed", 0)])
    qtbot.addWidget(form)

    form.set_values({"seed": 12345})

    assert form.seed_is_random() is False
    assert form.get_values()["seed"] == 12345


def test_a_form_that_does_not_pin_keeps_random_and_shows_a_fresh_seed_over_a_loaded_one(
        qtbot):
    form = ParamForm([ParamDef("seed", "Seed", "seed", 0)], pins_reused_seed=False)
    qtbot.addWidget(form)

    form.set_values({"seed": 12345})

    shown = form.get_values()["seed"]
    assert form.seed_is_random() is True
    assert shown != 12345
    assert form.get_values()["seed"] == shown


def test_a_form_that_does_not_pin_locks_the_items_own_seed_when_random_is_unticked(qtbot):
    form = ParamForm([ParamDef("seed", "Seed", "seed", 0)], pins_reused_seed=False)
    qtbot.addWidget(form)
    form.set_values({"seed": 12345})
    form.show_item({"seed": 12345})

    _clicked_random(form)

    assert form.get_values()["seed"] == 12345


def test_a_setting_with_no_field_is_kept_for_the_rerun_but_never_shown(qtbot):
    form = ParamForm([ParamDef("seed", "Seed", "seed", 0)])
    qtbot.addWidget(form)
    form.set_values({"seed": 5, "vae": "example.vae.safetensors"})

    labels = {lbl.text() for lbl in form.findChildren(QLabel)}
    assert "vae" not in labels
    assert "example.vae.safetensors" not in labels
    assert form.get_values()["vae"] == "example.vae.safetensors"


def _field_cell_of(form, key):
    field = _field_of(form, key)
    for fl in form.findChildren(QFormLayout):
        for r in range(fl.rowCount()):
            item = fl.itemAt(r, QFormLayout.ItemRole.FieldRole)
            if item is not None and item.layout() is not None:
                if item.layout().indexOf(field) != -1:
                    return item.layout()
    return None


def _field_of(form, key):
    return form._dim_stacks.get(key, form._widgets[key])


def test_seed_copy_button_sits_left_of_the_random_tick(qtbot):
    form = ParamForm([ParamDef("seed", "Seed", "seed", 0)])
    qtbot.addWidget(form)
    cell = _field_cell_of(form, "seed")
    copy_i = cell.indexOf(form._copy_buttons["seed"])
    random_i = cell.indexOf(form._randomize_checks["seed"])
    assert 0 <= copy_i < random_i


def _seed_form(qtbot, history, **kwargs):
    form = ParamForm([ParamDef("seed", "Seed", "seed", 0)],
                     seed_history=SeedHistory(lambda key: history, lambda item: None),
                     **kwargs)
    qtbot.addWidget(form)
    return form, form._widgets["seed"]


def test_a_seed_drops_down_the_seeds_used_most_recent_first(qtbot):
    form, field = _seed_form(qtbot, [SeedUse(30, None), SeedUse(20, None)])

    field.showPopup()

    assert [field.itemText(row) for row in range(field.count())] == ["30", "20"]
    field.hidePopup()


def test_a_seed_used_several_times_in_a_row_is_listed_once_for_the_stretch(qtbot):
    form, field = _seed_form(qtbot, [SeedUse(5, None), SeedUse(5, None), SeedUse(6, None),
                                     SeedUse(5, None)])

    field.showPopup()

    assert [field.itemText(row) for row in range(field.count())] == ["5", "6", "5"]
    field.hidePopup()


def _red_square(tmp_path):
    return square(tmp_path, "red")


def test_each_seed_in_the_dropdown_wears_a_thumbnail_of_what_it_made(qtbot, tmp_path):
    form, field = _seed_form(qtbot, [SeedUse(30, _red_square(tmp_path))])
    field.showPopup()

    row = painted_row(field, 0)

    assert row.height() > 2 * field.fontMetrics().height()
    assert row.pixelColor(row.height() // 2, row.height() // 2) == QColor("red")
    field.hidePopup()


def test_a_stretch_is_one_row_wearing_each_of_its_thumbnails_newest_on_top(qtbot, tmp_path):
    form, field = _seed_form(qtbot, [SeedUse(5, square(tmp_path, "red")),
                                     SeedUse(5, square(tmp_path, "blue")),
                                     SeedUse(6, None)])
    field.showPopup()

    stretch, single = painted_row(field, 0), painted_row(field, 1)

    pitch = single.height()
    assert stretch.height() == 2 * pitch
    assert stretch.pixelColor(pitch // 2, pitch // 2) == QColor("red")
    assert stretch.pixelColor(pitch // 2, pitch + pitch // 2) == QColor("blue")
    field.hidePopup()


def _lettering_in(row: QImage, *, right_of: int) -> list[QPoint]:
    return [QPoint(x, y) for y in range(row.height()) for x in range(right_of, row.width())
            if row.pixelColor(x, y).lightness() > 180]


def test_a_stretch_is_braced_between_its_thumbnails_and_its_seed(qtbot):
    form, field = _seed_form(qtbot, [SeedUse(5, None), SeedUse(5, None), SeedUse(6, None)])
    field.showPopup()

    stretch = painted_row(field, 0, under_the_mouse=True)
    single = painted_row(field, 1, under_the_mouse=True)

    pitch = single.height()
    seed_starts_at = min(point.x() for point in _lettering_in(single, right_of=pitch))
    assert any(point.x() < seed_starts_at for point in _lettering_in(stretch, right_of=pitch))
    field.hidePopup()


def test_a_stretch_prints_its_seed_once_beside_the_middle_of_its_thumbnails(qtbot):
    form, field = _seed_form(qtbot, [SeedUse(5, None), SeedUse(5, None), SeedUse(5, None),
                                     SeedUse(6, None)])
    field.showPopup()

    stretch = painted_row(field, 0, under_the_mouse=True)
    single = painted_row(field, 1, under_the_mouse=True)

    seed_starts_at = min(point.x() for point in _lettering_in(single, right_of=single.height()))
    seed = [point.y() for point in _lettering_in(stretch, right_of=seed_starts_at)]
    assert max(seed) - min(seed) < single.height()
    assert abs((max(seed) + min(seed)) / 2 - stretch.height() / 2) <= 3
    field.hidePopup()


def test_a_thumbnail_in_the_dropdown_is_set_in_from_the_edges_of_its_row(qtbot, tmp_path):
    form, field = _seed_form(qtbot, [SeedUse(30, _red_square(tmp_path))])
    field.showPopup()

    row = painted_row(field, 0)

    middle = row.height() // 2
    assert row.pixelColor(0, middle) != QColor("red")
    assert row.pixelColor(middle, 0) != QColor("red")
    assert row.pixelColor(middle, row.height() - 1) != QColor("red")
    field.hidePopup()


def test_a_thumbnail_keeps_its_own_colors_on_the_row_under_the_mouse(qtbot, tmp_path):
    form, field = _seed_form(qtbot, [SeedUse(30, _red_square(tmp_path))])
    field.showPopup()

    row = painted_row(field, 0, under_the_mouse=True)

    assert row.pixelColor(row.height() // 2, row.height() // 2) == QColor("red")
    field.hidePopup()


@pytest.mark.parametrize("size, beside, within", [
    ((400, 800), lambda middle, edge: (edge, middle), lambda middle, edge: (middle, edge + 4)),
    ((800, 400), lambda middle, edge: (middle, edge), lambda middle, edge: (edge + 4, middle)),
])
def test_a_seed_nothing_was_made_with_shows_a_blank_of_the_shape_it_would_make(
        qtbot, size, beside, within):
    form, field = _seed_form(qtbot, [SeedUse(30, None, size)])
    field.showPopup()

    row = painted_row(field, 0)

    middle, edge = row.height() // 2, 5
    assert row.pixelColor(*beside(middle, edge)) == QColor("black")
    assert row.pixelColor(*within(middle, edge)) != QColor("black")
    field.hidePopup()


def _bounds_of(image: QImage, color: str, *, left_of: int) -> QRect:
    wanted = QColor(color)
    xs, ys = [], []
    for y in range(image.height()):
        for x in range(min(left_of, image.width())):
            if image.pixelColor(x, y) == wanted:
                xs.append(x)
                ys.append(y)
    return QRect(QPoint(min(xs), min(ys)), QPoint(max(xs), max(ys)))


@pytest.mark.parametrize("size", [(800, 400), (400, 800), (512, 512)])
def test_the_question_mark_on_a_blank_nearly_fills_it(qtbot, size):
    form, field = _seed_form(qtbot, [SeedUse(30, None, size)])
    field.showPopup()

    row = painted_row(field, 0)

    mark = _bounds_of(row, TEXT_MUTED, left_of=row.height())
    blank = _bounds_of(row, BORDER_DEFAULT, left_of=row.height()).united(mark)
    assert max(mark.width() / blank.width(), mark.height() / blank.height()) >= 0.75
    field.hidePopup()


def test_the_dropdown_opens_wide_enough_for_a_whole_seed_beside_its_thumbnail(qtbot):
    form, field = _seed_form(qtbot, [SeedUse(20, None), SeedUse((1 << 63) - 1, None)])
    form.resize(160, 400)
    form.show()

    field.showPopup()

    view = field.view()
    option = QStyleOptionViewItem()
    widest = field.itemDelegate().sizeHint(option, field.model().index(1, 0))
    assert view.viewport().width() >= widest.width()
    field.hidePopup()


def test_opening_the_dropdown_is_no_edit_of_the_seed_in_the_field(qtbot):
    form, field = _seed_form(qtbot, [SeedUse(30, None), SeedUse(20, None)])
    form.set_values({"seed": 12345})
    edits = []
    form.changed.connect(lambda: edits.append(field.currentText()))

    field.showPopup()

    assert form.get_values()["seed"] == 12345
    assert edits == []
    field.hidePopup()


@pytest.mark.parametrize("pins_reused_seed", [True, False])
def test_picking_a_seed_from_the_dropdown_puts_it_in_the_field_and_pins_it(
        qtbot, pins_reused_seed):
    form, field = _seed_form(qtbot, [SeedUse(30, None), SeedUse(20, None)],
                             pins_reused_seed=pins_reused_seed)
    field.showPopup()
    view = field.view()

    qtbot.mouseClick(view.viewport(), Qt.MouseButton.LeftButton,
                     pos=view.visualRect(field.model().index(1, 0)).center())

    assert form.seed_is_random() is False
    assert form.get_values()["seed"] == 20


def test_a_typed_seed_is_never_finished_off_as_a_longer_one_from_the_dropdown(qtbot):
    form, field = _seed_form(qtbot, [SeedUse(1234, None)])
    form.show()
    field.showPopup()
    field.hidePopup()
    form.activateWindow()
    field.lineEdit().setFocus()
    qtbot.waitUntil(field.lineEdit().hasFocus)
    field.lineEdit().clear()

    qtbot.keyClicks(field.lineEdit(), "12")

    assert form.get_values()["seed"] == 12


def _middle_of(pixmap):
    image = pixmap.toImage()
    return image.pixelColor(image.width() // 2, image.height() // 2)


def test_the_closed_seed_shows_the_thumbnail_of_the_item_its_seed_came_from(qtbot, tmp_path):
    form = ParamForm([ParamDef("seed", "Seed", "seed", 0)])
    qtbot.addWidget(form)
    form.set_values({"seed": 42})

    form.show_item({"seed": 42}, _red_square(tmp_path))

    assert _middle_of(form._widgets["seed"]._thumbnail.pixmap()) == QColor("red")


def test_the_closed_seed_shows_a_blank_of_the_tabs_shape_for_a_seed_nothing_made(qtbot):
    form = ParamForm([ParamDef("seed", "Seed", "seed", 0),
                      ParamDef("width", "Width", "int", 400, max_val=4096),
                      ParamDef("height", "Height", "int", 800, max_val=4096)])
    qtbot.addWidget(form)

    image = form._widgets["seed"]._thumbnail.pixmap()

    assert abs(image.height() - 2 * image.width()) <= 1


def test_the_derived_size_follows_the_field_the_workflow_sizes_itself_off(qtbot):
    form = ParamForm([ParamDef("input_image", "Image", "image", ""),
                      ParamDef("video", "Video to Perform", "video", "")],
                     size_deriver=lambda values: (864, 480) if values.get("video") else None,
                     size_source="video")
    qtbot.addWidget(form)
    assert form._dim_value_labels["width"].text() == "—"

    form._widgets["video"].set_item("C:/library/videos/videos/scene one.mp4")

    assert (form._dim_value_labels["width"].text(), form._dim_value_labels["height"].text()) == ("864", "480")
    assert form._unlock_btn.toolTip() == "Unlock to override the size derived from the video to perform"


def test_the_closed_seed_takes_the_start_images_shape_the_moment_it_is_picked(qtbot):
    form = ParamForm([ParamDef("input_image", "Start Image", "image", ""),
                      ParamDef("seed", "Seed", "seed", 0)],
                     size_deriver=lambda values: (400, 800) if values.get("input_image") else None)
    qtbot.addWidget(form)

    form._widgets["input_image"].set_item("frame.png")

    image = form._widgets["seed"]._thumbnail.pixmap()
    assert abs(image.height() - 2 * image.width()) <= 1


def test_a_seed_picked_from_the_dropdown_keeps_its_thumbnail_closed(qtbot, tmp_path):
    form, field = _seed_form(qtbot, [SeedUse(30, _red_square(tmp_path)), SeedUse(20, None)])
    field.showPopup()
    view = field.view()

    qtbot.mouseClick(view.viewport(), Qt.MouseButton.LeftButton,
                     pos=view.visualRect(field.model().index(0, 0)).center())

    assert _middle_of(field._thumbnail.pixmap()) == QColor("red")


def test_picking_anywhere_on_a_stretch_takes_its_seed_with_its_newest_thumbnail(qtbot, tmp_path):
    form, field = _seed_form(qtbot, [SeedUse(30, square(tmp_path, "red")),
                                     SeedUse(30, square(tmp_path, "blue")),
                                     SeedUse(20, None)])
    field.showPopup()
    view = field.view()
    stretch = view.visualRect(field.model().index(0, 0))

    qtbot.mouseClick(view.viewport(), Qt.MouseButton.LeftButton,
                     pos=QPoint(stretch.center().x(), stretch.bottomLeft().y() - 4))

    assert field.currentText() == "30"
    assert _middle_of(field._thumbnail.pixmap()) == QColor("red")


def test_the_closed_seeds_thumbnail_stands_the_fields_height_and_clear_of_its_number(qtbot):
    form, field = _seed_form(qtbot, [])
    form.setFont(make_font(FONT_UI, SIZE_HEADING))
    form.resize(430, 300)
    form.show()
    QApplication.processEvents()

    image = field._thumbnail.geometry()
    number = field.lineEdit().geometry()

    assert image.height() >= field.height() - 8
    assert number.x() + field.lineEdit().textMargins().left() >= image.right()


class _HeightWhenShown(QObject):
    def __init__(self, popup):
        super().__init__(popup)
        self.height = None
        popup.installEventFilter(self)

    def eventFilter(self, watched, event):
        if event.type() == QEvent.Type.Show and self.height is None:
            self.height = watched.height()
        return False


def _opened_height(qtbot, history) -> int:
    form, field = _seed_form(qtbot, history)
    form.show()
    shown = _HeightWhenShown(field.view().parentWidget())
    field.showPopup()
    field.hidePopup()
    return shown.height


def test_a_stretch_leaves_the_dropdown_the_height_it_always_opens_at(qtbot):
    singles = [SeedUse(seed, None) for seed in range(20)]

    with_a_stretch = _opened_height(qtbot, [SeedUse(99, None)] * 30 + singles)

    assert with_a_stretch == _opened_height(qtbot, singles)


def test_a_dropdown_opening_upward_still_meets_its_field(qtbot):
    form, field = _seed_form(qtbot, [SeedUse(99, None)] * 30 + [SeedUse(1, None)])
    form.show()
    screen = QApplication.primaryScreen().availableGeometry()
    form.move(form.x(), screen.bottomLeft().y() - form.frameGeometry().height() + 1)

    field.showPopup()

    popup = field.view().parentWidget().geometry()
    assert 0 <= field.mapToGlobal(QPoint(0, 0)).y() - popup.bottomLeft().y() <= 2
    field.hidePopup()


def test_a_stretch_too_tall_for_one_row_carries_on_in_the_next(qtbot):
    form, field = _seed_form(qtbot, [SeedUse(5, None)] * 3000 + [SeedUse(6, None)])
    form.show()
    field.showPopup()
    view, model = field.view(), field.model()

    pitch = view.visualRect(model.index(field.count() - 1, 0)).height()
    stretch_rows = range(field.count() - 1)
    assert {field.itemText(row) for row in stretch_rows} == {"5"}
    assert sum(len(field.itemData(row, thumbnail_dropdown.THUMBNAILS_ROLE)) for row in stretch_rows) == 3000
    assert all(view.visualRect(model.index(row, 0)).height()
               == pitch * len(field.itemData(row, thumbnail_dropdown.THUMBNAILS_ROLE)) for row in stretch_rows)
    field.hidePopup()


def test_a_stretch_taller_than_the_list_scrolls_a_little_at_a_time(qtbot):
    form, field = _seed_form(qtbot, [SeedUse(5, None)] * 30 + [SeedUse(6, None)])
    form.show()
    field.showPopup()
    view = field.view()

    view.verticalScrollBar().triggerAction(QAbstractSlider.SliderAction.SliderSingleStepAdd)

    stretch = view.visualRect(field.model().index(0, 0))
    assert stretch.top() < 0 < stretch.bottomLeft().y()
    field.hidePopup()


@pytest.mark.parametrize("seed_of", [lambda n: n, lambda n: 5])
def test_a_long_history_reads_thumbnails_only_for_the_seeds_on_screen(qtbot, monkeypatch,
                                                                     seed_of):
    read = []
    monkeypatch.setattr(thumbnail_dropdown, "fitted_thumbnail",
                        lambda path, side, gray: read.append(path))
    history = [SeedUse(seed_of(n), f"thumbs/{n}.jpg") for n in range(3000)]
    form, field = _seed_form(qtbot, history)
    form.show()

    field.showPopup()
    qtbot.waitUntil(lambda: bool(read))
    QApplication.processEvents()

    assert 0 < len(set(read)) <= 2 * field.maxVisibleItems()
    field.hidePopup()


def _clicked_random(form, key="seed"):
    form._randomize_checks[key].click()


def test_ticking_random_puts_a_fresh_seed_in_the_field_and_says_so(qtbot):
    form = ParamForm([ParamDef("seed", "Seed", "seed", 0)])
    qtbot.addWidget(form)
    form.set_values({"seed": 42})
    drawn = []
    form.seed_drawn.connect(lambda key, seed: drawn.append((key, seed)))

    _clicked_random(form)

    assert form.seed_is_random() is True
    assert drawn == [("seed", form.get_values()["seed"])]
    assert drawn[0][1] != 42


def test_unticking_random_puts_back_the_seed_of_the_item_on_display(qtbot):
    form = ParamForm([ParamDef("seed", "Seed", "seed", 0)])
    qtbot.addWidget(form)
    form.show_item({"seed": 42})

    _clicked_random(form)

    assert form.seed_is_random() is False
    assert form.get_values()["seed"] == 42


def test_turning_random_on_from_outside_draws_and_off_puts_the_items_seed_back(qtbot):
    form = ParamForm([ParamDef("seed", "Seed", "seed", 0)])
    qtbot.addWidget(form)
    form.set_values({"seed": 42})
    form.show_item({"seed": 42})

    form.set_seed_random(True)
    drawn = form.get_values()["seed"]
    form.set_seed_random(False)

    assert drawn != 42
    assert form.get_values()["seed"] == 42


def test_a_form_sized_from_its_input_says_what_size_it_would_make(qtbot):
    form = ParamForm([ParamDef("input_image", "Input Image", "image", ""),
                      ParamDef("noise_seed", "Seed", "seed", 0)],
                     size_deriver=lambda values: (464, 912))
    qtbot.addWidget(form)

    assert form.output_size() == (464, 912)


def _label_cell(form, key):
    title = param_sections.section_title(key)
    row = form._present_keys[title].index(key)
    return form._sections[title].content_form().itemAt(
        row, QFormLayout.ItemRole.LabelRole).widget()


def _label_beside(form, key):
    return _label_cell(form, key).findChild(ElidingLabel)


def _dimension_defs():
    return [
        ParamDef("width", "Width", "int", 1280, min_val=64, max_val=4096, step=64),
        ParamDef("height", "Height", "int", 720, min_val=64, max_val=4096, step=64),
    ]


def _size_heading_wears(form, orientation) -> bool:
    mark = form._sections["Size"]._header._mark
    return mark is not None and mark.toImage() == icons.shape_mark(orientation).toImage()


def test_the_size_heading_wears_the_frame_of_the_shape_the_size_makes(qtbot):
    form = ParamForm(_dimension_defs())
    qtbot.addWidget(form)
    assert _size_heading_wears(form, LANDSCAPE)

    form._widgets["width"].setValue(704)
    form._widgets["height"].setValue(1280)
    assert _size_heading_wears(form, PORTRAIT)


def test_a_square_size_wears_the_landscape_frame_and_says_it_is_square(qtbot):
    form = ParamForm(_dimension_defs())
    qtbot.addWidget(form)
    form._widgets["height"].setValue(1280)

    assert _size_heading_wears(form, LANDSCAPE)
    assert form._sections["Size"]._header.toolTip() == "Square, so it goes under Landscape"


def test_swap_dimensions_button_exchanges_width_and_height(qtbot):
    form = ParamForm(_dimension_defs())
    qtbot.addWidget(form)
    assert form._swap_dimensions_btn is not None
    form._swap_dimensions_btn.click()
    vals = form.get_values()
    assert vals["width"] == 720
    assert vals["height"] == 1280


def test_no_swap_button_when_workflow_has_no_dimensions(qtbot):
    form = ParamForm([ParamDef("steps", "Steps", "int", 50, min_val=1, max_val=200)])
    qtbot.addWidget(form)
    assert form._swap_dimensions_btn is None


def test_swapping_dimensions_emits_changed(qtbot):
    form = ParamForm(_dimension_defs())
    qtbot.addWidget(form)
    fired = []
    form.changed.connect(lambda: fired.append(True))
    form._swap_dimensions_btn.click()
    assert fired


def test_swap_button_sits_between_the_rows_and_left_of_the_labels(qtbot):
    form = ParamForm([
        ParamDef("prompt", "Positive Prompt", "str", "", multiline=True),
        *_dimension_defs(),
    ])
    form.setFont(make_font(FONT_UI, SIZE_HEADING))
    qtbot.addWidget(form)
    form._sections["Size"].set_collapsed(False)
    form.resize(400, 320)
    with qtbot.waitExposed(form):
        form.show()

    btn = form._swap_dimensions_btn.geometry()
    width = form._widgets["width"].geometry()
    height = form._widgets["height"].geometry()

    assert width.center().y() < btn.center().y() < height.center().y()
    assert btn.right() <= width.left()
    assert btn.right() <= _label_cell(form, "width").geometry().left()
    assert btn.right() <= _label_cell(form, "height").geometry().left()


def _image_def():
    return ParamDef("input_image", "Input Image", "image", "")


def _sized_form(qtbot, size=(864, 480)):
    form = ParamForm(
        [_image_def()],
        size_deriver=lambda params: size if params.get("input_image") else None,
    )
    qtbot.addWidget(form)
    return form


def test_locked_dimensions_render_as_plain_values_not_input_fields(qtbot):
    form = _sized_form(qtbot)
    assert "width" in form._present_keys["Size"]
    assert "height" in form._present_keys["Size"]
    assert form._unlock_btn is not None
    assert form._dimensions_hint is not None
    for key in ("width", "height"):
        stack = form._dim_stacks[key]
        assert stack.currentIndex() == 0
        assert stack.currentWidget() is form._dim_value_labels[key]
        assert form._dim_value_labels[key].objectName() == "readonlyParamValue"
    assert form._dim_value_labels["width"].text() == "—"


def test_a_derived_size_names_the_image_it_is_read_from_as_the_form_does(qtbot):
    form = ParamForm([ParamDef("input_image", "Start Image", "image", "")],
                     size_deriver=lambda params: None)
    qtbot.addWidget(form)

    assert form._dimensions_hint.text() == "Sized from the start image. Unlock to override."
    assert form._unlock_btn.toolTip() == "Unlock to override the size derived from the start image"
    form._unlock_btn.setChecked(True)
    assert form._unlock_btn.toolTip() == "Re-lock to the size derived from the start image"


def test_unlocking_swaps_the_plain_value_for_an_editable_field(qtbot):
    form = _sized_form(qtbot)
    form._unlock_btn.setChecked(True)
    for key in ("width", "height"):
        stack = form._dim_stacks[key]
        assert stack.currentIndex() == 1
        assert stack.currentWidget() is form._widgets[key]


def test_unlock_toggle_carries_a_padlock_icon_that_flips(qtbot):
    form = _sized_form(qtbot)
    assert form._unlock_btn.isCheckable()
    def wears(mark: str) -> bool:
        return (form._unlock_btn.icon().pixmap(BUTTON_ICON).toImage()
                == qt_icon(mark).pixmap(BUTTON_ICON).toImage())

    assert wears("lock")
    form._unlock_btn.setChecked(True)
    assert wears("unlock")


def test_unlock_toggle_floats_free_and_never_shrinks_a_dimension_field(qtbot):
    form = _sized_form(qtbot)
    assert form._unlock_btn.parent() is form._sections["Size"].content()
    assert _field_cell_of(form, "width").indexOf(form._unlock_btn) == -1
    assert _field_cell_of(form, "height").indexOf(form._unlock_btn) == -1


def test_unlock_toggle_sits_between_the_rows_and_clears_the_labels(qtbot):
    form = _sized_form(qtbot)
    form.setStyleSheet(build_stylesheet())
    form.setFont(make_font(FONT_UI, SIZE_HEADING))
    form._sections["Size"].set_collapsed(False)
    form.resize(420, 380)
    with qtbot.waitExposed(form):
        form.show()

    btn = form._unlock_btn.geometry()
    top = form._dim_stacks["width"].geometry()
    lower = form._dim_stacks["height"].geometry()
    assert top.center().y() < btn.center().y() < lower.center().y()

    assert btn.right() <= _label_cell(form, "width").geometry().left()
    assert btn.right() <= _label_cell(form, "height").geometry().left()
    assert btn.right() <= top.left()


def test_a_size_read_off_the_start_image_puts_that_shape_on_the_size_heading(qtbot):
    form = _sized_form(qtbot, size=(464, 912))
    assert form._sections["Size"]._header._mark is None

    form._widgets["input_image"].set_item("frame.png")
    assert _size_heading_wears(form, PORTRAIT)


def test_derived_dimensions_track_the_input_image(qtbot):
    form = _sized_form(qtbot, size=(864, 480))
    form._widgets["input_image"].set_item("frame.png")
    assert form._dim_value_labels["width"].text() == "864"
    assert form._dim_value_labels["height"].text() == "480"
    assert form._widgets["width"].value() == 864
    assert form._widgets["height"].value() == 480


def test_locked_derived_dimensions_stay_out_of_the_values(qtbot):
    form = _sized_form(qtbot)
    form._widgets["input_image"].set_item("frame.png")
    values = form.get_values()
    assert "width" not in values
    assert "height" not in values


def test_unlocking_lets_the_user_override_the_size(qtbot):
    form = _sized_form(qtbot)
    form._widgets["input_image"].set_item("frame.png")
    fired = []
    form.changed.connect(lambda: fired.append(True))

    form._unlock_btn.setChecked(True)
    assert fired
    assert form._dim_stacks["width"].currentIndex() == 1
    form._widgets["width"].setValue(1024)
    form._widgets["height"].setValue(576)

    values = form.get_values()
    assert values["width"] == 1024
    assert values["height"] == 576


def test_a_size_the_user_is_overriding_is_not_overwritten_when_the_input_image_changes(qtbot):
    form = _sized_form(qtbot, size=(864, 480))
    form._widgets["input_image"].set_item("frame.png")
    form._unlock_btn.setChecked(True)
    form._widgets["width"].setValue(1024)

    form._widgets["input_image"].set_item("other.png")

    assert form._widgets["width"].value() == 1024


def test_every_label_elides_so_no_long_name_sets_a_floor_under_the_whole_form(qtbot):
    form = _sized_form(qtbot)

    assert form._labels
    assert all(isinstance(label, ElidingLabel) for label in form._labels.values())


def test_relocking_drops_the_override_and_restores_the_derived_size(qtbot):
    form = _sized_form(qtbot, size=(864, 480))
    form._widgets["input_image"].set_item("frame.png")
    form._unlock_btn.setChecked(True)
    form._widgets["width"].setValue(1024)
    form._widgets["height"].setValue(576)

    form._unlock_btn.setChecked(False)
    assert "width" not in form.get_values()
    assert form._dim_stacks["width"].currentIndex() == 0
    assert form._dim_value_labels["width"].text() == "864"


def test_set_values_with_a_size_override_unlocks_and_shows_it(qtbot):
    form = _sized_form(qtbot)
    form.set_values({"input_image": "frame.png", "width": 720, "height": 400})
    assert form._dimensions_unlocked() is True
    assert form._widgets["width"].value() == 720
    assert form.get_values()["height"] == 400


def test_set_values_without_an_override_relocks_onto_the_derived_size(qtbot):
    form = _sized_form(qtbot, size=(864, 480))
    form.set_values({"input_image": "frame.png", "width": 720, "height": 400})
    form.set_values({"input_image": "other.png"})
    assert form._dimensions_unlocked() is False
    assert "width" not in form.get_values()
    assert form._widgets["width"].value() == 864


def test_manual_size_workflow_has_no_unlock_control(qtbot):
    form = ParamForm(_dimension_defs())
    qtbot.addWidget(form)
    assert form._unlock_btn is None
    assert form._swap_dimensions_btn is not None


@pytest.fixture
def sample_defs():
    return [
        ParamDef("prompt", "Prompt", "str", "hello", multiline=True),
        ParamDef("steps", "Steps", "int", 50, min_val=1, max_val=200),
        ParamDef("cfg", "CFG", "float", 7.5, min_val=0.0, max_val=30.0, step=0.5),
        ParamDef("sampler", "Sampler", "dropdown", "euler", options=["euler", "dpm"]),
    ]


def test_an_untouched_form_reads_back_every_default(qtbot, sample_defs):
    form = ParamForm(sample_defs)
    qtbot.addWidget(form)
    vals = form.get_values()
    assert vals["prompt"] == "hello"
    assert vals["steps"] == 50
    assert vals["cfg"] == 7.5
    assert vals["sampler"] == "euler"


def test_param_form_set_values_updates_widgets(qtbot, sample_defs):
    form = ParamForm(sample_defs)
    qtbot.addWidget(form)
    form.set_values({"prompt": "new text", "steps": 20, "cfg": 3.0, "sampler": "dpm"})
    vals = form.get_values()
    assert vals["prompt"] == "new text"
    assert vals["steps"] == 20
    assert vals["cfg"] == 3.0
    assert vals["sampler"] == "dpm"


def test_a_float_field_keeps_the_second_decimal_place(qtbot, sample_defs):
    form = ParamForm(sample_defs)
    qtbot.addWidget(form)

    form.set_values({"cfg": 0.85})

    assert form.get_values()["cfg"] == 0.85


@pytest.mark.parametrize("pd, written, read_back", [
    (ParamDef("enhance", "Enhance", "bool", True), False, False),
    (ParamDef("name", "Name", "str", ""), "a made-up name", "a made-up name"),
    (ParamDef("positive_prompt", "Positive Prompt", "str", "", multiline=True),
     "a lighthouse\nat dusk", "a lighthouse\nat dusk"),
    (ParamDef("seed", "Seed", "seed", 0), 680387713615965, 680387713615965),
    (ParamDef("steps", "Steps", "int", 20, min_val=1, max_val=200), 42, 42),
    (ParamDef("cfg", "CFG", "float", 7.5, min_val=0.0, max_val=30.0, step=0.5), 0.85, 0.85),
    (ParamDef("sampler", "Sampler", "dropdown", "euler", options=["euler", "dpm"]), "dpm", "dpm"),
    (ParamDef("input_image", "Input Image", "image", ""), "  frame.png ", "frame.png"),
    (ParamDef("voice_sample", "Voice Sample", "audio", ""), " sample.wav ", "sample.wav"),
    (ParamDef("video", "Video to Perform", "video", ""), " scene one.mp4 ", "scene one.mp4"),
    (ParamDef("width", "Width", "int", 512, min_val=64, max_val=2048, step=64,
              options=[512, 768]), 768.0, 768),
    (ParamDef("frame_rate", "Frame Rate", "float", 24.0, min_val=1.0, max_val=120.0,
              step=1.0, options=[16, 24, 60], unit="fps"), 60, 60.0),
    (ParamDef("frame_count", "Duration", "int", 81, min_val=5, max_val=161, step=4,
              options=[1, 5, 10], unit="s", rate=16.0), 21, 21),
])
def test_every_kind_of_setting_reads_back_as_the_row_stores_it(qtbot, pd, written, read_back):
    form = ParamForm([pd])
    qtbot.addWidget(form)

    form.set_values({pd.key: written})

    value = form.get_values()[pd.key]
    assert value == read_back
    assert type(value) is type(read_back)


def test_a_number_field_with_no_stated_ceiling_takes_a_large_value(qtbot):
    form = ParamForm([ParamDef("steps", "Steps", "int", 20)])
    qtbot.addWidget(form)

    form.set_values({"steps": 5000})

    assert form.get_values()["steps"] == 5000


def test_set_values_preserves_params_without_a_field(qtbot, sample_defs):
    form = ParamForm(sample_defs)
    qtbot.addWidget(form)
    form.set_values({"steps": 30, "vae_name": "custom.safetensors"})
    assert form.get_values()["vae_name"] == "custom.safetensors"
    assert form.get_values()["vae_name"] == "custom.safetensors"
    assert form.get_values()["steps"] == 30


def test_set_values_replaces_stale_passthrough(qtbot, sample_defs):
    form = ParamForm(sample_defs)
    qtbot.addWidget(form)
    form.set_values({"vae_name": "first.safetensors"})
    form.set_values({"clip_name": "second.safetensors"})
    values = form.get_values()
    assert values["clip_name"] == "second.safetensors"
    assert "vae_name" not in values


def test_set_values_keeps_a_combo_value_absent_from_the_options(qtbot):
    form = ParamForm([ParamDef("lora", "LoRA", "dropdown", "a", options=["a", "b"])])
    qtbot.addWidget(form)
    form.set_values({"lora": "gone.safetensors"})
    assert form.get_values()["lora"] == "gone.safetensors"


def test_combo_default_absent_from_options_is_still_selected(qtbot):
    form = ParamForm([ParamDef("lora", "LoRA", "dropdown", "default.safetensors",
                               options=["a.safetensors", "b.safetensors"])])
    qtbot.addWidget(form)
    assert form.get_values()["lora"] == "default.safetensors"


def test_a_model_dropdown_shows_each_files_title_and_the_form_keeps_its_name(
        qtbot, titled_models):
    titled_models({"example_model": "Example Model v2"})
    form = ParamForm([ParamDef("checkpoint", "Model", "dropdown", "example_model.safetensors",
                               options=["example_model.safetensors",
                                        "example_other.safetensors"])])
    qtbot.addWidget(form)
    field = form._widgets["checkpoint"]

    assert [field.itemText(row) for row in range(field.count())] == [
        "Example Model v2", "example_other"]
    assert form.get_values()["checkpoint"] == "example_model.safetensors"
    form.set_values({"checkpoint": "example_other.safetensors"})
    assert (field.currentText(), form.get_values()["checkpoint"]) == (
        "example_other", "example_other.safetensors")


def test_a_fresh_form_shows_the_seed_its_first_generate_will_use(qtbot):
    form = ParamForm([ParamDef("seed", "Seed", "seed", 12345)])
    qtbot.addWidget(form)

    shown = form.get_values()["seed"]

    assert form.seed_is_random() is True
    assert shown != 12345
    assert form.get_values()["seed"] == shown


def test_param_form_emits_changed_on_edit(qtbot):
    form = ParamForm([ParamDef("steps", "Steps", "int", 10, min_val=1, max_val=100)])
    qtbot.addWidget(form)
    fired = []
    form.changed.connect(lambda: fired.append(True))
    form.set_values({"steps": 42})
    assert fired


def test_seed_is_random_reflects_the_tick(qtbot):
    form = ParamForm([ParamDef("seed", "Seed", "seed", 0)])
    qtbot.addWidget(form)
    assert form.seed_is_random() is True
    form.set_values({"seed": 42})
    assert form.seed_is_random() is False


def test_set_seed_random_re_ticks_it(qtbot):
    form = ParamForm([ParamDef("seed", "Seed", "seed", 0)])
    qtbot.addWidget(form)
    form.set_values({"seed": 42})
    assert form.seed_is_random() is False
    form.set_seed_random(True)
    assert form.seed_is_random() is True
    form.set_seed_random(False)
    assert form.seed_is_random() is False


def test_param_form_seed_handles_64bit_values(qtbot):
    defs = [ParamDef("seed", "Seed", "seed", 0)]
    form = ParamForm(defs)
    qtbot.addWidget(form)
    big_seed = 680387713615965
    form.set_values({"seed": big_seed})
    vals = form.get_values()
    assert vals["seed"] == big_seed


def _browse_the_zone(form, key):
    actions = {action.text(): action for action in form._widgets[key].menu().actions()}
    actions["Browse..."].trigger()


def _stub_file_dialog(monkeypatch, chosen, captured=None):
    def fake(parent, caption, directory, filt):
        if captured is not None:
            captured["dir"] = directory
            captured["caption"] = caption
        return chosen, ""

    monkeypatch.setattr(file_pick.QFileDialog, "getOpenFileName", fake)


def test_param_form_browse_button_picks_any_file(qtbot, monkeypatch):
    _stub_file_dialog(monkeypatch, "C:/Users/Example/Pictures/cat.png")

    form = ParamForm([ParamDef("input_image", "Input Image", "image", "")])
    qtbot.addWidget(form)
    _browse_the_zone(form, "input_image")

    assert form.get_values()["input_image"] == "C:/Users/Example/Pictures/cat.png"


def test_param_form_browse_cancel_keeps_existing_image(qtbot, monkeypatch):
    _stub_file_dialog(monkeypatch, "")

    form = ParamForm([ParamDef("input_image", "Input Image", "image", "preset.png")])
    qtbot.addWidget(form)
    _browse_the_zone(form, "input_image")

    assert form.get_values()["input_image"] == "preset.png"


def test_param_form_browse_defaults_to_input_dir(qtbot, monkeypatch):
    captured = {}
    _stub_file_dialog(monkeypatch, "", captured)

    form = ParamForm([ParamDef("input_image", "Input Image", "image", "")])
    qtbot.addWidget(form)
    _browse_the_zone(form, "input_image")

    assert captured["dir"] == str(pf.COMFYUI_INPUT_DIR)


def test_param_form_browse_opens_in_the_folder_the_param_names(qtbot, monkeypatch, tmp_path):
    poses = tmp_path / "custom_poses"
    poses.mkdir()
    captured = {}
    _stub_file_dialog(monkeypatch, "", captured)

    form = ParamForm(
        [ParamDef("input_image", "Structure Image", "image", "", browse_dir=poses)]
    )
    qtbot.addWidget(form)
    _browse_the_zone(form, "input_image")

    assert captured["dir"] == str(poses)


def test_param_form_browse_falls_back_when_the_named_folder_is_absent(
    qtbot, monkeypatch, tmp_path
):
    captured = {}
    _stub_file_dialog(monkeypatch, "", captured)

    form = ParamForm([
        ParamDef("input_image", "Structure Image", "image", "",
                 browse_dir=tmp_path / "not_installed"),
    ])
    qtbot.addWidget(form)
    _browse_the_zone(form, "input_image")

    assert captured["dir"] == str(pf.COMFYUI_INPUT_DIR)


def test_the_browse_dialog_is_titled_with_the_fields_own_name(qtbot, monkeypatch):
    captured = {}
    _stub_file_dialog(monkeypatch, "", captured)
    form = ParamForm([ParamDef("input_image", "Structure Image", "image", "")])
    qtbot.addWidget(form)

    _browse_the_zone(form, "input_image")

    assert captured["caption"] == "Select Structure Image"


def test_param_form_browse_starts_at_current_image_location(qtbot, monkeypatch, tmp_path):
    img = tmp_path / "cat.png"
    img.write_bytes(b"\x89PNG")
    captured = {}
    _stub_file_dialog(monkeypatch, "", captured)

    form = ParamForm([ParamDef("input_image", "Input Image", "image", str(img))])
    qtbot.addWidget(form)
    _browse_the_zone(form, "input_image")

    assert captured["dir"] == str(img)


def test_input_image_value_is_cleaned_of_invisible_wrapping_characters(qtbot):
    form = ParamForm([ParamDef("input_image", "Input Image", "image", "")])
    qtbot.addWidget(form)
    zwsp = chr(0x200B)
    wrapped = f"image/{zwsp}sdxl_{zwsp}t2i_{zwsp}00792_{zwsp}.{zwsp}png  "
    form.set_values({"input_image": wrapped})

    assert form.get_values()["input_image"] == "image/sdxl_t2i_00792_.png"


def test_fields_are_grouped_into_collapsible_sections(qtbot):
    form = ParamForm([
        ParamDef("positive_prompt", "Positive Prompt", "str", "", multiline=True),
        ParamDef("seed", "Seed", "seed", 0),
        ParamDef("steps", "Steps", "int", 20),
    ])
    qtbot.addWidget(form)
    assert isinstance(form._sections["Prompts"], CollapsibleSection)
    assert "positive_prompt" in form._present_keys["Prompts"]
    assert "seed" in form._present_keys["Seed"]
    assert "steps" in form._present_keys["Calibration"]


def test_empty_sections_are_hidden(qtbot):
    form = ParamForm([ParamDef("seed", "Seed", "seed", 0)])
    qtbot.addWidget(form)
    with qtbot.waitExposed(form):
        form.show()
    assert form._sections["Seed"].isHidden() is False
    assert form._sections["Prompts"].isHidden() is True
    assert form._sections["Video"].isHidden() is True


def test_prompts_and_seed_start_open_the_rest_collapsed(qtbot):
    form = ParamForm(WORKFLOW_REGISTRY["wan22_i2v"].param_definitions())
    qtbot.addWidget(form)
    assert form._sections["Prompts"].is_collapsed() is False
    assert form._sections["Seed"].is_collapsed() is False
    assert form._sections["Models & LoRAs"].is_collapsed() is True
    assert form._sections["Calibration"].is_collapsed() is True
    assert form._sections["Video"].is_collapsed() is True
    assert form._sections["Sound"].is_collapsed() is True


def test_fields_lay_out_in_canonical_order_not_param_definitions_order(qtbot):
    wf = WORKFLOW_REGISTRY["sdxl_t2i"]
    defs = wf.param_definitions()
    form = ParamForm(defs, hidden_keys=wf.enhance_keys())
    qtbot.addWidget(form)
    shown = [d.key for d in defs if d.key not in wf.enhance_keys()]
    assert form._keys_in_order() == sorted(shown, key=param_sections.key_rank)
    assert form._keys_in_order() != shown


def test_shared_sections_appear_in_the_same_order_across_workflows(qtbot):
    def section_sequence(name):
        form = ParamForm(WORKFLOW_REGISTRY[name].param_definitions())
        qtbot.addWidget(form)
        return [title for title, keys in form._present_keys.items() if keys]

    sdxl = section_sequence("sdxl_t2i")
    i2v = section_sequence("wan22_i2v")
    shared = [t for t in sdxl if t in i2v]
    assert [t for t in i2v if t in sdxl] == shared


def test_hidden_params_get_no_field(qtbot):
    wf = WORKFLOW_REGISTRY["sdxl_t2i"]
    form = ParamForm(wf.param_definitions(), hidden_keys=wf.enhance_keys())
    qtbot.addWidget(form)
    shown = set(form._keys_in_order())
    assert shown.isdisjoint(set(wf.enhance_keys()))
    assert "enhance" not in form._widgets


def test_every_field_and_its_label_carry_the_params_help(qtbot):
    wf = WORKFLOW_REGISTRY["sdxl_t2i"]
    definitions = wf.param_definitions()
    form = ParamForm(definitions, hidden_keys=wf.enhance_keys())
    qtbot.addWidget(form)
    for pd in definitions:
        if pd.key in form._widgets:
            assert form._widgets[pd.key].toolTip() == definition_help(pd), pd.key
    steps = next(pd for pd in definitions if pd.key == "steps")
    assert _label_beside(form, "steps").toolTip() == definition_help(steps)


def test_a_field_with_a_good_range_says_it_in_its_tooltip(qtbot):
    steps = ParamDef("steps", "Steps", ParamType.INT, 30, min_val=1, max_val=100, good=(20, 40))
    form = ParamForm([steps])
    qtbot.addWidget(form)
    assert "Good range: 20–40." in form._widgets["steps"].toolTip()
    assert "Good range: 20–40." in _label_beside(form, "steps").toolTip()


def test_a_label_with_no_help_spells_out_its_whole_name_on_hover(qtbot):
    mystery = ParamDef("mystery_number", "A Mystery Setting Too Long To Show", ParamType.INT, 1)
    form = ParamForm([mystery])
    qtbot.addWidget(form)
    assert _label_beside(form, "mystery_number").toolTip() == "A Mystery Setting Too Long To Show"


def test_a_pages_recommendation_takes_the_good_ranges_place_until_it_goes(qtbot):
    steps = ParamDef("steps", "Steps", ParamType.INT, 30, min_val=1, max_val=100, good=(20, 40))
    form = ParamForm([steps])
    qtbot.addWidget(form)

    form.explain({"steps": "Example Model's page recommends 25–35 steps."})
    recommended = (form._widgets["steps"].toolTip(), _label_beside(form, "steps").toolTip())
    form.explain({})
    left_alone = (form._widgets["steps"].toolTip(), _label_beside(form, "steps").toolTip())

    assert all(tip.endswith(" Example Model's page recommends 25–35 steps.")
               and "Good range" not in tip for tip in recommended)
    assert all(tip.endswith(" Good range: 20–40.") for tip in left_alone)


def test_hidden_params_stay_at_the_workflow_default_whatever_is_loaded(qtbot):
    wf = WORKFLOW_REGISTRY["sdxl_t2i"]
    form = ParamForm(wf.param_definitions(), hidden_keys=wf.enhance_keys())
    qtbot.addWidget(form)
    assert form.get_values()["enhance"] is False

    form.set_values(dict(wf.default_params(), enhance=True, enhance_steps=44))

    values = form.get_values()
    assert values["enhance"] is False
    assert values["enhance_steps"] == wf.default_params()["enhance_steps"]
    assert "enhance" in values


def test_a_section_with_no_fields_stays_hidden_whatever_a_config_carries_for_it(qtbot):
    form = ParamForm(WORKFLOW_REGISTRY["wan22_t2i"].param_definitions())
    qtbot.addWidget(form)
    with qtbot.waitExposed(form):
        form.show()

    form.set_values({"unet_high": "example_high.safetensors",
                     "unet_low": "example_low.safetensors"})

    assert form._sections["Models & LoRAs"].isHidden() is True


def _rate_def(default=24.0):
    return ParamDef("frame_rate", "Frame Rate", "float", default,
                    min_val=1.0, max_val=120.0, step=1.0,
                    options=[16, 24, 60], unit="fps")


def test_a_numeric_param_with_presets_is_an_editable_dropdown_that_emits_the_number(qtbot):
    form = ParamForm([_rate_def()])
    qtbot.addWidget(form)
    dropdown = form._widgets["frame_rate"]
    assert isinstance(dropdown, PresetDropdown)
    assert dropdown.currentText() == "24 fps"
    assert form.get_values()["frame_rate"] == 24.0

    changes = []
    form.changed.connect(lambda: changes.append(1))
    dropdown.setCurrentText("30")
    assert form.get_values()["frame_rate"] == 30.0
    assert changes

    form.set_values({"frame_rate": 60})
    assert dropdown.currentText() == "60 fps"
    assert form.get_values()["frame_rate"] == 60.0


def test_a_typed_number_past_the_range_is_clamped_and_shown_clamped_once_the_edit_ends(qtbot):
    form = ParamForm([_rate_def()])
    qtbot.addWidget(form)
    with qtbot.waitExposed(form):
        form.show()
    dropdown = form._widgets["frame_rate"]
    dropdown.lineEdit().setFocus()
    dropdown.setCurrentText("500")
    assert form.get_values()["frame_rate"] == 120.0
    qtbot.keyClick(dropdown.lineEdit(), Qt.Key.Key_Return)
    assert dropdown.currentText() == "120 fps"


def _video_defs(max_frames=161):
    return [
        ParamDef("frame_count", "Duration", "int", 81, min_val=5, max_val=max_frames,
                 step=4, options=[1, 5, 10], unit="s", rate=16.0),
        ParamDef("frame_rate", "Frame Rate", "float", 16.0, min_val=16.0, max_val=112.0,
                 step=16.0, options=[16, 32, 48], unit="fps"),
    ]


def _preset_states(dropdown) -> dict:
    model = dropdown.model()
    return {dropdown.itemText(i): model.item(i).isEnabled() for i in range(dropdown.count())}


def test_a_duration_this_model_cannot_render_is_offered_grayed_out(qtbot):
    form = ParamForm(_video_defs(max_frames=81))
    qtbot.addWidget(form)
    duration = form._widgets["frame_count"]

    assert _preset_states(duration) == {"1 s": True, "5 s": True, "10 s": False}
    assert "5 s" in duration.model().item(2).toolTip()


def test_the_presets_a_model_can_reach_are_all_left_alone(qtbot):
    form = ParamForm(_video_defs())
    qtbot.addWidget(form)

    assert all(_preset_states(form._widgets["frame_count"]).values())
    assert all(_preset_states(form._widgets["frame_rate"]).values())


def test_a_frame_count_is_shown_and_edited_as_seconds_at_the_models_own_rate(qtbot):
    form = ParamForm(_video_defs())
    qtbot.addWidget(form)
    duration = form._widgets["frame_count"]
    assert [duration.itemText(i) for i in range(duration.count())] == ["1 s", "5 s", "10 s"]
    assert duration.currentText() == "5 s"
    assert form.get_values()["frame_count"] == 81

    duration.setCurrentText("10")
    assert form.get_values()["frame_count"] == 161

    form.set_values({"frame_count": 21})
    assert duration.currentText() == "1.3 s"
    assert form.get_values()["frame_count"] == 21


def test_the_frames_a_duration_asks_for_dont_move_when_the_frame_rate_does(qtbot):
    form = ParamForm(_video_defs())
    qtbot.addWidget(form)
    assert form.get_values()["frame_count"] == 81
    form._widgets["frame_rate"].setCurrentText("48")
    assert form._widgets["frame_count"].currentText() == "5 s"
    assert form.get_values() == {"frame_count": 81, "frame_rate": 48.0}


def test_a_loaded_frame_count_is_shown_as_the_seconds_it_really_runs(qtbot):
    form = ParamForm(_video_defs())
    qtbot.addWidget(form)
    form.set_values({"frame_count": 121, "frame_rate": 24.0})
    assert form._widgets["frame_count"].currentText() == "7.6 s"
    assert form._widgets["frame_rate"].currentText() == "32 fps"
    assert form.get_values()["frame_count"] == 121


def test_a_duration_the_model_cannot_render_settles_to_what_it_can_once_the_edit_ends(qtbot):
    form = ParamForm(_video_defs())
    qtbot.addWidget(form)
    with qtbot.waitExposed(form):
        form.show()
    duration = form._widgets["frame_count"]

    duration.lineEdit().setFocus()
    duration.setCurrentText("30")
    assert form.get_values()["frame_count"] == 161
    qtbot.keyClick(duration.lineEdit(), Qt.Key.Key_Return)
    assert duration.currentText() == "10 s"


def test_a_frame_rate_the_interpolator_cannot_reach_settles_onto_one_it_can(qtbot):
    form = ParamForm(_video_defs())
    qtbot.addWidget(form)
    with qtbot.waitExposed(form):
        form.show()
    rate = form._widgets["frame_rate"]

    rate.lineEdit().setFocus()
    rate.setCurrentText("60")
    assert form.get_values()["frame_rate"] == 64.0
    qtbot.keyClick(rate.lineEdit(), Qt.Key.Key_Return)
    assert rate.currentText() == "64 fps"


def _scene_defs():
    return [
        ParamDef("positive_prompt", "Positive Prompt", "str", "", multiline=True),
        ParamDef("negative_prompt", "Negative Prompt", "str", "", multiline=True),
        ParamDef("scene_frames", "Scenes", "scenes", [81], min_val=5, max_val=961, step=4,
                 options=[1, 5, 10, 15, 30, 60], unit="s", rate=16.0),
        ParamDef("scene_lines", "Lines", "lines", [""]),
        ParamDef("frame_count", "Duration", "int", 81, min_val=5, max_val=961, step=4,
                 options=[1, 5, 10, 15, 30, 60], unit="s", rate=16.0),
    ]


def test_a_story_starts_as_one_scene_whose_length_is_the_videos(qtbot):
    form = ParamForm(_scene_defs())
    qtbot.addWidget(form)
    editor = form._widgets["scene_frames"]
    assert (form._widgets["positive_prompt"] is editor is form._widgets["negative_prompt"]
            is form._widgets["scene_lines"])
    assert len(editor.fields("positive_prompt")) == 1
    assert form.get_values() == {"positive_prompt": "", "negative_prompt": "",
                                 "scene_frames": [81], "scene_lines": [""], "frame_count": 81}
    assert form._present_keys["Prompts"] == ["scene_frames"]


def test_a_scenes_prompts_mark_unpaired_parentheses_and_its_spoken_line_does_not(qtbot):
    form = ParamForm(_scene_defs())
    qtbot.addWidget(form)
    editor = form._widgets["scene_frames"]
    (prompt,) = editor.fields("positive_prompt")
    (line,) = editor.fields("scene_lines")

    prompt.setPlainText("a (dog")
    assert problem_to_resolve([prompt]) == RESOLVE_UNPAIRED_PARENTHESES

    prompt.setPlainText("a (dog)")
    line.setPlainText("oh :)")
    assert problem_to_resolve([line]) is None


def test_leaving_a_scenes_prompt_tidies_what_was_typed_and_leaves_its_spoken_line(qtbot):
    form = ParamForm(_scene_defs())
    qtbot.addWidget(form)
    editor = form._widgets["scene_frames"]
    (prompt,) = editor.fields("positive_prompt")
    (line,) = editor.fields("scene_lines")
    for field in (prompt, line):
        QApplication.sendEvent(field, QFocusEvent(QEvent.Type.FocusIn))
        field.setPlainText("a  b")
        QApplication.sendEvent(field, QFocusEvent(QEvent.Type.FocusOut))

    assert prompt.toPlainText() == "a b"
    assert line.toPlainText() == "a  b"


def test_adding_a_scene_gives_it_its_own_prompt_and_length_and_the_clip_adds_up(qtbot):
    form = ParamForm(_scene_defs())
    qtbot.addWidget(form)
    editor = form._widgets["scene_frames"]
    editor.add_scene()
    editor.fields("positive_prompt")[0].setPlainText("she waves")
    editor.fields("positive_prompt")[1].setPlainText("she turns")
    [scene.length for scene in editor._scenes][1].setCurrentText("10")
    values = form.get_values()
    assert values["positive_prompt"] == "she waves\n---\nshe turns"
    assert values["scene_frames"] == [81, 161]
    assert values["frame_count"] == 241


def test_each_scene_keeps_out_its_own_and_a_new_one_starts_from_the_last(qtbot):
    form = ParamForm(_scene_defs())
    qtbot.addWidget(form)
    editor = form._widgets["scene_frames"]
    editor.fields("negative_prompt")[0].setPlainText("blurry")
    editor.add_scene()
    assert editor.fields("negative_prompt")[1].toPlainText() == "blurry"
    editor.fields("negative_prompt")[1].setPlainText("blurry, hats")
    assert form.get_values()["negative_prompt"] == "blurry\n---\nblurry, hats"


def test_a_stored_story_fills_one_field_per_scene(qtbot):
    form = ParamForm(_scene_defs())
    qtbot.addWidget(form)
    stored = {"positive_prompt": "a\n---\nb\n---\nc", "negative_prompt": "x\n---\ny\n---\nz",
              "scene_frames": [161, 81, 161], "scene_lines": ["hi", "", "bye"], "frame_count": 401}
    form.set_values(stored)
    editor = form._widgets["scene_frames"]
    assert [field.toPlainText() for field in editor.fields("positive_prompt")] == ["a", "b", "c"]
    assert [field.toPlainText() for field in editor.fields("negative_prompt")] == ["x", "y", "z"]
    assert [dropdown.currentText() for dropdown in [scene.length for scene in editor._scenes]] == ["10 s", "5 s", "10 s"]
    assert [field.toPlainText() for field in editor.fields("scene_lines")] == ["hi", "", "bye"]
    assert form.get_values() == stored


def test_settings_from_before_scenes_load_as_one_scene_of_the_clips_length(qtbot):
    form = ParamForm(_scene_defs())
    qtbot.addWidget(form)
    form.set_values({"positive_prompt": "one shot", "negative_prompt": "blurry", "frame_count": 121})
    editor = form._widgets["scene_frames"]
    assert [field.toPlainText() for field in editor.fields("positive_prompt")] == ["one shot"]
    assert [field.toPlainText() for field in editor.fields("negative_prompt")] == ["blurry"]
    assert [dropdown.currentText() for dropdown in [scene.length for scene in editor._scenes]] == ["7.6 s"]
    values = form.get_values()
    assert (values["scene_frames"], values["frame_count"]) == ([121], 121)
    assert values["negative_prompt"] == "blurry"


def test_a_whole_clip_negative_carries_on_into_every_scene_of_a_story(qtbot):
    form = ParamForm(_scene_defs())
    qtbot.addWidget(form)
    form.set_values({"positive_prompt": "a\n---\nb\n---\nc", "negative_prompt": "blurry",
                     "scene_frames": [81, 81, 81], "frame_count": 241})
    editor = form._widgets["scene_frames"]
    assert [field.toPlainText() for field in editor.fields("negative_prompt")] == ["blurry"] * 3


def test_removing_a_scene_shortens_the_clip_and_the_last_one_stays(qtbot):
    form = ParamForm(_scene_defs())
    qtbot.addWidget(form)
    editor = form._widgets["scene_frames"]
    editor.add_scene()
    editor.add_scene()
    assert form.get_values()["frame_count"] == 81 + 80 + 80
    editor.remove_scene(1)
    assert form.get_values()["scene_frames"] == [81, 81]
    editor.remove_scene(0)
    assert form.get_values()["scene_frames"] == [81]
    assert not [scene.remove for scene in editor._scenes][0].isEnabled()


def test_a_story_has_no_length_row_and_still_records_the_scenes_total(qtbot):
    form = ParamForm(_scene_defs())
    qtbot.addWidget(form)
    editor = form._widgets["scene_frames"]
    editor.add_scene()
    [scene.length for scene in editor._scenes][0].setCurrentText("10")

    assert "frame_count" not in form._present_keys["Video"]
    assert form.get_values()["frame_count"] == 241


def test_scene_prompts_are_text_fields_for_find_and_read_back_as_one_story(qtbot):
    form = ParamForm(_scene_defs())
    qtbot.addWidget(form)
    editor = form._widgets["scene_frames"]
    editor.add_scene()
    editor.fields("positive_prompt")[0].setPlainText("a")
    editor.fields("positive_prompt")[1].setPlainText("b")
    editor.fields("negative_prompt")[1].setPlainText("n")
    assert editor.fields("positive_prompt")[0] in form.text_fields()
    assert editor.fields("positive_prompt")[1] in form.text_fields()
    assert editor.fields("negative_prompt")[1] in form.text_fields()
    assert form.get_values()["positive_prompt"] == "a\n---\nb"
    assert form.get_values()["negative_prompt"] == "\n---\nn"


def test_each_box_on_a_tile_says_what_it_is(qtbot):
    form = ParamForm(_scene_defs())
    qtbot.addWidget(form)
    scene = form._widgets["scene_frames"]._scenes[0]
    captions = {label.text() for label in scene.findChildren(ElidingLabel)}
    assert {"Positive Prompt", "Negative Prompt", "Her Lines"} <= captions
    assert scene.fields["negative_prompt"].toolTip() == param_help("negative_prompt")
    assert "spoken" in scene.fields["scene_lines"].placeholderText().lower()


def test_a_scene_with_a_line_shuts_its_prompts_down_and_says_why(qtbot):
    form = ParamForm(_scene_defs())
    qtbot.addWidget(form)
    scene = form._widgets["scene_frames"]._scenes[0]
    assert not scene.speaking()
    for key in ("positive_prompt", "negative_prompt"):
        assert not scene.fields[key].isReadOnly()
        assert not scene.fields[key].property("inert")

    scene.fields["scene_lines"].setPlainText("Come in.")
    assert scene.speaking()
    for key, caption in (("positive_prompt", "Positive Prompt"),
                         ("negative_prompt", "Negative Prompt")):
        field = scene.fields[key]
        assert field.isReadOnly()
        assert field.property("inert") is True
        assert scene.captions[key].property("inert") is True
        assert field.toolTip() == SPEAKING_HELP
        assert scene.captions[key].text() == caption + SPEAKING_NOTE
        assert scene.captions[key].toolTip() == SPEAKING_HELP


def test_clearing_a_scenes_line_gives_its_prompts_back(qtbot):
    form = ParamForm(_scene_defs())
    qtbot.addWidget(form)
    scene = form._widgets["scene_frames"]._scenes[0]
    scene.fields["positive_prompt"].setPlainText("she pours a glass")
    scene.fields["scene_lines"].setPlainText("Come in.")
    scene.fields["scene_lines"].setPlainText("   ")
    assert not scene.speaking()
    for key, caption in (("positive_prompt", "Positive Prompt"),
                         ("negative_prompt", "Negative Prompt")):
        assert not scene.fields[key].isReadOnly()
        assert scene.fields[key].property("inert") is False
        assert scene.captions[key].property("inert") is False
        assert scene.fields[key].toolTip() == param_help(key)
        assert scene.captions[key].text() == caption
    assert scene.fields["positive_prompt"].toPlainText() == "she pours a glass"


def test_stored_spoken_settings_open_with_their_prompts_already_shut_down(qtbot):
    form = ParamForm(_scene_defs())
    qtbot.addWidget(form)
    form.set_values({"positive_prompt": story_of(["a", "b"]), "negative_prompt": "",
                     "scene_frames": [81, 81], "scene_lines": ["", "Sit."],
                     "frame_count": 161})
    silent, spoken = form._widgets["scene_frames"]._scenes
    assert (silent.speaking(), spoken.speaking()) == (False, True)
    assert not silent.fields["positive_prompt"].isReadOnly()
    assert spoken.fields["positive_prompt"].isReadOnly()


def test_a_shut_down_prompt_actually_renders_dim(qtbot):

    form = ParamForm(_scene_defs())
    qtbot.addWidget(form)
    form.setStyleSheet(build_stylesheet())
    scene = form._widgets["scene_frames"]._scenes[0]
    field = scene.fields["positive_prompt"]
    field.setPlainText("MMMM MMMM MMMM")
    field.resize(240, 60)

    def colors():
        image = field.grab().toImage()
        counts: dict[tuple, int] = {}
        for y in range(image.height()):
            for x in range(image.width()):
                c = image.pixelColor(x, y)
                key = (c.red(), c.green(), c.blue())
                counts[key] = counts.get(key, 0) + 1
        return {rgb for rgb, n in counts.items() if n > 100}

    written = colors()
    scene.fields["scene_lines"].setPlainText("Come in.")
    spoken = colors()
    primary = (TEXT_PRIMARY.red(), TEXT_PRIMARY.green(), TEXT_PRIMARY.blue())
    muted = (TEXT_MUTED.red(), TEXT_MUTED.green(), TEXT_MUTED.blue())
    assert primary in written
    assert muted not in written
    assert muted in spoken
    assert primary not in spoken


def test_a_workflow_that_cannot_speak_shows_no_lines_box(qtbot):
    form = ParamForm([pd for pd in _scene_defs() if pd.key != "scene_lines"])
    qtbot.addWidget(form)
    editor = form._widgets["scene_frames"]
    editor.add_scene()
    for scene in editor._scenes:
        assert "scene_lines" not in scene.fields
        assert "Her Lines" not in {label.text() for label in scene.findChildren(ElidingLabel)}
    assert editor.lines() == []
    assert "scene_lines" not in form.get_values()


def test_settings_whose_lone_scene_disagrees_with_the_video_follow_the_video(qtbot):
    form = ParamForm(_scene_defs())
    qtbot.addWidget(form)
    form.set_values({"positive_prompt": "x", "frame_count": 121, "scene_frames": [81]})
    editor = form._widgets["scene_frames"]
    assert [dropdown.currentText() for dropdown in [scene.length for scene in editor._scenes]] == ["7.6 s"]
    assert form.get_values()["frame_count"] == 121



def _voice_defs():
    return [
        ParamDef("voice", "Voice", "dropdown", "Vivian", options=list(VOICE_OPTIONS)),
        ParamDef("voice_sample", "Voice Sample", "audio", ""),
        ParamDef("voice_sample_text", "Voice Sample Says", "str", "", multiline=True),
    ]


def _row_visible(form, key):
    title = param_sections.section_title(key)
    return form._sections[title].content_form().isRowVisible(form._present_keys[title].index(key))


def test_the_speaking_settings_show_only_while_a_scene_has_a_line(qtbot):
    form = ParamForm(_scene_defs() + _voice_defs() + [
        ParamDef("unet_s2v", "Speaking Model", "dropdown", "example_s2v.safetensors",
                 options=["example_s2v.safetensors"]),
    ])
    qtbot.addWidget(form)
    form._widgets["voice"].setCurrentText(CUSTOM_VOICE)
    speaking_rows = ("voice", "voice_sample", "voice_sample_text", "unet_s2v")
    assert not any(_row_visible(form, key) for key in speaking_rows)

    form._widgets["scene_frames"].fields("scene_lines")[0].setPlainText("Come in.")

    assert all(_row_visible(form, key) for key in speaking_rows)


def test_the_sound_prompts_are_shut_down_while_every_scene_speaks(qtbot):
    form = ParamForm(_scene_defs() + [
        ParamDef("audio_prompt", "Positive Prompt", "str", "", multiline=True),
        ParamDef("audio_negative_prompt", "Negative Prompt", "str", "", multiline=True),
    ])
    qtbot.addWidget(form)
    editor = form._widgets["scene_frames"]
    editor.add_scene()
    editor.fields("scene_lines")[0].setPlainText("Come in.")
    assert _in_use_with(form, "audio_prompt", param_help("audio_prompt"))

    editor.fields("scene_lines")[1].setPlainText("Sit down.")

    assert _shut_down_with(form, "audio_prompt", EVERY_SCENE_SPEAKS_HELP)
    assert _shut_down_with(form, "audio_negative_prompt", EVERY_SCENE_SPEAKS_HELP)

    editor.fields("scene_lines")[1].setPlainText("")

    assert _in_use_with(form, "audio_negative_prompt", param_help("audio_negative_prompt"))


def _shut_down_with(form, key, tip):
    label = form._labels[key]
    return (_row_visible(form, key) and label.property("inert") is True and label.toolTip() == tip
            and all(box.isReadOnly() and box.property("inert") is True and box.toolTip() == tip
                    for box in form._widgets[key].boxes()))


def _in_use_with(form, key, tip):
    label = form._labels[key]
    return (_row_visible(form, key) and label.property("inert") is False and label.toolTip() == tip
            and all(not box.isReadOnly() and box.property("inert") is False
                    and box.toolTip() == tip for box in form._widgets[key].boxes()))


def test_the_things_to_avoid_are_shut_down_while_prompt_strength_is_one(qtbot):
    form = ParamForm([
        ParamDef("negative_prompt", "Negative Prompt", "str", "", multiline=True),
        ParamDef("cfg", "Prompt Strength", "float", 1.0, min_val=0.0, max_val=30.0, step=0.1),
    ])
    qtbot.addWidget(form)
    assert _shut_down_with(form, "negative_prompt", STRENGTH_ONE_HELP)

    form._widgets["cfg"].setValue(3.5)

    assert _in_use_with(form, "negative_prompt", param_help("negative_prompt"))


def test_the_things_to_avoid_are_shut_down_until_either_pass_pushes_the_prompt(qtbot):
    form = ParamForm([
        ParamDef("negative_prompt", "Negative Prompt", "str", "", multiline=True),
        ParamDef("cfg_high", "Prompt Strength (First Pass)", "float", 1.0,
                 min_val=0.0, max_val=30.0, step=0.1),
        ParamDef("cfg_low", "Prompt Strength (Second Pass)", "float", 1.0,
                 min_val=0.0, max_val=30.0, step=0.1),
    ])
    qtbot.addWidget(form)
    assert _shut_down_with(form, "negative_prompt", BOTH_STRENGTHS_ONE_HELP)

    form._widgets["cfg_low"].setValue(2.0)

    assert _in_use_with(form, "negative_prompt", param_help("negative_prompt"))


def _scene_text_state(scene, key):
    field, caption = scene.fields[key], scene.captions[key]
    return (field.isHidden(), field.isReadOnly(), field.property("inert"),
            field.toolTip(), caption.toolTip(), caption.text())


def _scene_form_at_strength_one():
    return ParamForm(_scene_defs() + [
        ParamDef("cfg", "Prompt Strength", "float", 1.0, min_val=0.0, max_val=30.0, step=0.1),
    ])


_SHUT_DOWN_AVOID = (False, True, True, STRENGTH_ONE_HELP, STRENGTH_ONE_HELP, "Negative Prompt")
_IN_USE_AVOID = (False, False, False, param_help("negative_prompt"), param_help("negative_prompt"),
                 "Negative Prompt")


def test_a_scenes_things_to_avoid_are_shut_down_while_prompt_strength_is_one(qtbot):
    form = _scene_form_at_strength_one()
    qtbot.addWidget(form)
    scene = form._widgets["scene_frames"]._scenes[0]
    assert _scene_text_state(scene, "negative_prompt") == _SHUT_DOWN_AVOID
    assert not scene.fields["positive_prompt"].isReadOnly()

    form._widgets["cfg"].setValue(3.5)

    assert _scene_text_state(scene, "negative_prompt") == _IN_USE_AVOID


def test_a_scene_added_at_prompt_strength_one_comes_up_with_its_things_to_avoid_shut_down(qtbot):
    form = _scene_form_at_strength_one()
    qtbot.addWidget(form)
    editor = form._widgets["scene_frames"]

    editor.add_scene()

    assert [_scene_text_state(scene, "negative_prompt") for scene in editor._scenes] == [
        _SHUT_DOWN_AVOID, _SHUT_DOWN_AVOID]


def test_a_speaking_scene_keeps_the_speaking_help_at_prompt_strength_one(qtbot):
    form = _scene_form_at_strength_one()
    qtbot.addWidget(form)
    scene = form._widgets["scene_frames"]._scenes[0]

    scene.fields["scene_lines"].setPlainText("Come in.")

    for key, caption in (("positive_prompt", "Positive Prompt"),
                         ("negative_prompt", "Negative Prompt")):
        assert _scene_text_state(scene, key) == (
            False, True, True, SPEAKING_HELP, SPEAKING_HELP, caption + SPEAKING_NOTE)

    scene.fields["scene_lines"].setPlainText("")

    assert not scene.fields["positive_prompt"].isReadOnly()
    assert _scene_text_state(scene, "negative_prompt") == _SHUT_DOWN_AVOID


@pytest.mark.parametrize("key", ["lora_high", "lora_low", "lora", "lora_2", "lora_3"])
def test_a_loras_strength_shows_only_while_it_has_a_lora(qtbot, key):
    strength = strength_key_of(key)
    form = ParamForm([
        ParamDef(key, "LoRA", "dropdown", "None", options=["None", "example_style.safetensors"]),
        ParamDef(strength, "LoRA Strength", "float", 1.0, min_val=0.0, max_val=2.0, step=0.05),
    ])
    qtbot.addWidget(form)
    assert not _row_visible(form, strength)

    lora = form._widgets[key]
    lora.setCurrentIndex(lora.findData("example_style.safetensors"))
    assert _row_visible(form, strength)

    form.set_values({key: "None"})
    assert not _row_visible(form, strength)


def test_the_voice_sample_rows_show_only_for_the_custom_voice(qtbot):
    form = ParamForm(_scene_defs() + _voice_defs())
    qtbot.addWidget(form)
    form._widgets["scene_frames"].fields("scene_lines")[0].setPlainText("Come in.")
    assert not _row_visible(form, "voice_sample")
    assert not _row_visible(form, "voice_sample_text")
    form._widgets["voice"].setCurrentText(CUSTOM_VOICE)
    assert _row_visible(form, "voice_sample")
    assert _row_visible(form, "voice_sample_text")
    form.set_values({"voice": "Serena"})
    assert not _row_visible(form, "voice_sample")
    form.set_values({"voice": CUSTOM_VOICE, "voice_sample": "C:/v/her.wav", "voice_sample_text": "Hi."})
    assert _row_visible(form, "voice_sample")
    assert form.get_values()["voice_sample"] == "C:/v/her.wav"


def test_a_voice_sample_is_picked_with_a_browse_button(qtbot, monkeypatch):
    asked = {}

    def fake(parent, caption, directory, kinds):
        asked.update(caption=caption, kinds=kinds)
        return "C:/v/her.wav", ""

    monkeypatch.setattr(file_pick.QFileDialog, "getOpenFileName", fake)
    form = ParamForm(_voice_defs())
    qtbot.addWidget(form)
    form._browse_buttons["voice_sample"].click()
    assert form._widgets["voice_sample"].text() == "C:/v/her.wav"
    assert "Voice Sample" in asked["caption"]
    assert "*.wav" in asked["kinds"]
    assert form.get_values()["voice_sample"] == "C:/v/her.wav"


def test_each_sampler_in_the_dropdown_explains_itself_on_hover(qtbot):
    form = ParamForm([ParamDef("sampler_name", "Sampler", "dropdown", "euler",
                               options=["euler", "euler_ancestral"])])
    qtbot.addWidget(form)
    dropdown = form._widgets["sampler_name"]
    tips = [dropdown.itemData(row, Qt.ItemDataRole.ToolTipRole) for row in range(dropdown.count())]
    assert tips == [option_help("sampler_name", "euler"),
                    option_help("sampler_name", "euler_ancestral")]
    assert all(tips)


def test_one_composition_focus_gives_both_passes_its_value(qtbot):
    form = ParamForm(WORKFLOW_REGISTRY["wan22_i2v"].param_definitions())
    qtbot.addWidget(form)

    form.set_values({"shift_high": 9.0, "shift_low": 5.0})
    assert (form.get_values()["shift_high"], form.get_values()["shift_low"]) == (9.0, 9.0)

    form._widgets["shift_high"].setValue(6.0)
    assert (form.get_values()["shift_high"], form.get_values()["shift_low"]) == (6.0, 6.0)


_STEPS_ADVICE = {"steps": Advice("Example Model's page recommends 20–40 steps.",
                                 value=50, fix=40)}


def test_a_setting_off_its_recommendation_wears_a_warning_with_the_advice(qtbot):
    form = ParamForm(WORKFLOW_REGISTRY["sdxl_t2i"].param_definitions())
    qtbot.addWidget(form)

    form.set_warnings(_STEPS_ADVICE)

    assert not form._warning_marks["steps"].isHidden()
    assert form._warning_marks["steps"].toolTip() == (
        "Example Model's page recommends 20–40 steps. Click to use 40.")
    assert form._warning_marks["cfg"].isHidden()
    form.set_warnings({})
    assert form._warning_marks["steps"].isHidden()


_SAMPLER_ADVICE = {"sampler_name": Advice("Example Model's page recommends euler_ancestral.",
                                          value="heun", fix="euler_ancestral")}


def test_a_section_warns_with_every_warning_inside_it_one_per_line(qtbot):
    form = ParamForm(WORKFLOW_REGISTRY["sdxl_t2i"].param_definitions())
    qtbot.addWidget(form)
    form.set_values({"steps": 50, "sampler_name": "heun"})

    form.set_warnings({**_SAMPLER_ADVICE, **_STEPS_ADVICE})

    calibration = form._sections["Calibration"].warning
    assert not calibration.isHidden()
    assert calibration.toolTip() == (
        "Steps: 50. Example Model's page recommends 20–40 steps. Click to use 40.\n"
        "Sampler: heun. Example Model's page recommends euler_ancestral. "
        "Click to use euler_ancestral.")
    assert form._sections["Models & LoRAs"].warning.isHidden()
    form.set_warnings({})
    assert calibration.isHidden()


def _laid_out(qtbot, form):
    qtbot.addWidget(form)
    for section in form._sections.values():
        section.set_collapsed(False)
    form.resize(640, 2400)
    with qtbot.waitExposed(form):
        form.show()
    return form


def _left(form, widget):
    return widget.mapTo(form, QPoint(0, 0)).x()


def test_clicking_a_warning_sets_its_setting_to_the_recommended_value(qtbot):
    form = _laid_out(qtbot, ParamForm(WORKFLOW_REGISTRY["sdxl_t2i"].param_definitions()))
    form.set_values({"steps": 50, "sampler_name": "heun"})
    form.set_warnings({**_STEPS_ADVICE, **_SAMPLER_ADVICE})

    qtbot.mouseClick(form._warning_marks["steps"], Qt.MouseButton.LeftButton)
    qtbot.mouseClick(form._warning_marks["sampler_name"], Qt.MouseButton.LeftButton)

    values = form.get_values()
    assert (values["steps"], values["sampler_name"]) == (40, "euler_ancestral")


_STRENGTH_ADVICE = {"lora_strength_high": Advice(
    "Example LoRA's page recommends a strength of 0.8–1.2.", value=1.5, fix=1.2)}
_PROMPT_STRENGTH_ADVICE = {"cfg_high": Advice("Example Model's page recommends 3–6.",
                                              value=9.0, fix=6.0)}


def _wan_form(qtbot):
    return _laid_out(qtbot, ParamForm(WORKFLOW_REGISTRY["wan22_i2v"].param_definitions(),
                                      size_deriver=lambda values: (464, 912)))


def test_clicking_a_sections_warning_resolves_every_warning_in_it_and_none_outside(qtbot):
    form = _wan_form(qtbot)
    form.set_values({"steps": 50, "cfg_high": 9.0, "lora_strength_high": 1.5})
    form.set_warnings({**_STEPS_ADVICE, **_PROMPT_STRENGTH_ADVICE, **_STRENGTH_ADVICE})

    qtbot.mouseClick(form._sections["Calibration"].warning, Qt.MouseButton.LeftButton)

    values = form.get_values()
    assert (values["steps"], values["cfg_high"], values["lora_strength_high"]) == (40, 6.0, 1.5)


def test_the_whole_forms_warnings_read_and_resolve_in_the_order_of_its_sections(qtbot):
    form = _wan_form(qtbot)
    form.set_values({"steps": 50, "lora_strength_high": 1.5})
    form.set_warnings({**_STEPS_ADVICE, **_STRENGTH_ADVICE})

    assert form.every_warning() == (
        "LoRA Strength 1 (First Pass): 1.5. Example LoRA's page recommends a strength of "
        "0.8–1.2. Click to use 1.2.\n"
        "Steps: 50. Example Model's page recommends 20–40 steps. Click to use 40.")
    form.resolve_every_warning()
    values = form.get_values()
    assert (values["steps"], values["lora_strength_high"]) == (40, 1.2)


def _duration_advice(form):
    return setting_advice({"frame_count": form.get_values()["frame_count"]}, form.definitions())


def test_a_storys_length_off_its_good_range_warns_beside_its_scenes(qtbot):
    form = _wan_form(qtbot)
    form.set_values({"positive_prompt": "a\n---\nb", "scene_frames": [81, 161]})

    form.set_warnings(_duration_advice(form))

    assert form._warning_marks["scene_frames"].toolTip() == (
        "Good range: 5–10 s. Click to use 10 s.")
    assert form.every_warning() == "Scenes: 15 s. Good range: 5–10 s. Click to use 10 s."


def test_the_scenes_tooltip_says_the_good_range_their_warning_holds_the_story_to(qtbot):
    form = ParamForm(WORKFLOW_REGISTRY["wan22_i2v"].param_definitions(),
                     size_deriver=lambda values: (464, 912))
    qtbot.addWidget(form)

    assert " Good range: 5–10 s. " in form._labels["scene_frames"].toolTip()


def test_clicking_the_warning_beside_scenes_shortens_the_last_scene_to_fit(qtbot):
    form = _wan_form(qtbot)
    form.set_values({"positive_prompt": "a\n---\nb", "scene_frames": [81, 161]})
    form.set_warnings(_duration_advice(form))

    qtbot.mouseClick(form._warning_marks["scene_frames"], Qt.MouseButton.LeftButton)

    values = form.get_values()
    assert (values["scene_frames"], values["frame_count"]) == ([81, 81], 161)


def test_resolving_a_warning_leaves_the_rest_of_the_form_as_it_was(qtbot):
    form = _wan_form(qtbot)
    form.set_values({"steps": 50, "example_extra": "kept", "width": 640, "height": 960})
    form.set_warnings(_STEPS_ADVICE)

    qtbot.mouseClick(form._warning_marks["steps"], Qt.MouseButton.LeftButton)

    values = form.get_values()
    assert (values["steps"], values.get("example_extra"), values.get("width"),
            values.get("height")) == (40, "kept", 640, 960)


_TRIGGER_WORD = {"lora": MissingTriggerWords("example_style.safetensors", ("exmplstyle",))}
_TRIGGER_WORD_SAID = ("Example Style 1.0's trigger word, exmplstyle, isn't in the Positive "
                      "Prompt. Click to add it.")


def _krea_form(qtbot):
    return _laid_out(qtbot, ParamForm(WORKFLOW_REGISTRY["krea2_t2i"].param_definitions()))


def test_a_missing_trigger_word_warns_beside_the_prompt_and_beside_its_lora(qtbot, titled_models):
    titled_models({"example_style": "Example Style 1.0"})
    form = _krea_form(qtbot)

    form.set_warnings(_TRIGGER_WORD)

    marks = [form._warning_marks[key] for key in ("positive_prompt", "lora")]
    assert [(mark.isHidden(), mark.toolTip()) for mark in marks] == [
        (False, _TRIGGER_WORD_SAID)] * 2


def test_a_trigger_word_clicked_in_goes_at_the_start_of_the_first_box_and_flows_on(qtbot):
    form = _laid_out(qtbot, ParamForm(WORKFLOW_REGISTRY["sdxl_t2i"].param_definitions()))
    form.show_readings({"positive_prompt": word_reading(3, READ_IN_PIECES)})
    form.set_values({"positive_prompt": f"a b c{BOX_BREAK}d"})
    form.set_warnings(_TRIGGER_WORD)

    qtbot.mouseClick(form._warning_marks["positive_prompt"], Qt.MouseButton.LeftButton)

    assert form.get_values()["positive_prompt"] == (
        f"exmplstyle, a{BOX_BREAK}b c d")


def test_a_requests_rewrite_flows_into_boxes_of_whole_words(qtbot):
    form = ParamForm(WORKFLOW_REGISTRY["sdxl_t2i"].param_definitions())
    qtbot.addWidget(form)
    form.show_readings({"positive_prompt": word_reading(3, READ_IN_PIECES),
                        "negative_prompt": word_reading(3, READ_IN_PIECES)})

    form.set_prompts("a b c d", "e f g h", typed=True)

    values = form.get_values()
    assert (values["positive_prompt"], values["negative_prompt"]) == (
        f"a b c{BOX_BREAK}d", f"e f g{BOX_BREAK}h")


@pytest.mark.parametrize("beside", ["positive_prompt", "lora"])
def test_clicking_a_trigger_words_warning_puts_the_word_at_the_start_of_the_prompt(qtbot, beside):
    form = _krea_form(qtbot)
    form.set_values({"positive_prompt": "a portrait, soft light"})
    form.set_warnings(_TRIGGER_WORD)

    qtbot.mouseClick(form._warning_marks[beside], Qt.MouseButton.LeftButton)

    assert form.get_values()["positive_prompt"] == "exmplstyle, a portrait, soft light"


def test_a_trigger_word_warning_beside_two_fields_is_one_line_of_each_warning_it_is_among(
        qtbot, titled_models):
    titled_models({"example_style": "Example Style 1.0"})
    form = _krea_form(qtbot)

    form.set_warnings(_TRIGGER_WORD)

    line = f"LoRA 1: Example Style 1.0. {_TRIGGER_WORD_SAID}"
    assert form.every_warning() == line
    assert [form._sections[title].warning.toolTip()
            for title in ("Prompts", "Models & LoRAs")] == [line, line]


def test_one_click_adds_once_a_word_two_loras_both_lack(qtbot):
    form = _wan_form(qtbot)
    form.set_values({"positive_prompt": "a portrait"})
    form.set_warnings({
        "lora_high": MissingTriggerWords("example_style_high.safetensors", ("exmplstyle",)),
        "lora_low": MissingTriggerWords("example_style_low.safetensors", ("exmplstyle",))})

    form.resolve_every_warning()

    assert form.get_values()["positive_prompt"] == "exmplstyle, a portrait"


def test_a_story_wears_its_trigger_word_warning_beside_its_scenes_and_each_scene_gets_the_word(
        qtbot):
    form = _wan_form(qtbot)
    form.set_values({"positive_prompt": "scene one\n---\nexmplstyle, scene two",
                     "scene_frames": [81, 81]})
    form.set_warnings({"lora_high": MissingTriggerWords("example_style.safetensors",
                                                        ("exmplstyle",), in_scenes=True)})

    qtbot.mouseClick(form._warning_marks["scene_frames"], Qt.MouseButton.LeftButton)

    assert form.get_values()["positive_prompt"] == (
        "exmplstyle, scene one\n---\nexmplstyle, scene two")


def test_the_scenes_warn_about_their_length_and_a_missing_trigger_word_on_two_lines(
        qtbot, titled_models):
    titled_models({"example_style": "Example Style 1.0"})
    form = _wan_form(qtbot)
    form.set_values({"positive_prompt": "a\n---\nb", "scene_frames": [81, 161]})

    form.set_warnings({**_duration_advice(form), "lora_high": _TRIGGER_WORD["lora"]})

    assert form._warning_marks["scene_frames"].toolTip() == (
        f"Good range: 5\N{EN DASH}10 s. Click to use 10 s.\n{_TRIGGER_WORD_SAID}")


def test_a_warning_mark_sits_left_of_its_label(qtbot):
    form = _laid_out(qtbot, ParamForm(WORKFLOW_REGISTRY["sdxl_t2i"].param_definitions()))

    form.set_warnings(_STEPS_ADVICE)
    QApplication.processEvents()

    mark = form._warning_marks["steps"]
    assert _left(form, mark) + mark.width() <= _left(form, _label_beside(form, "steps"))


def test_a_warning_appearing_moves_no_label_or_field(qtbot):
    form = _laid_out(qtbot, ParamForm(WORKFLOW_REGISTRY["sdxl_t2i"].param_definitions()))
    label, field = _label_beside(form, "steps"), form._widgets["steps"]
    before = (_left(form, label), field.geometry())

    form.set_warnings(_STEPS_ADVICE)
    QApplication.processEvents()

    assert (_left(form, label), field.geometry()) == before


def test_a_row_shown_again_keeps_its_warning_mark_hidden(qtbot):
    form = ParamForm(WORKFLOW_REGISTRY["wan22_i2v"].param_definitions())
    qtbot.addWidget(form)

    form.set_values({"lora_high": NO_LORA})
    form.set_values({"lora_high": "example_lora_high.safetensors"})

    assert _row_visible(form, "lora_strength_high")
    assert form._warning_marks["lora_strength_high"].isHidden()


def _shown_keys(form):
    return [key for keys in form._present_keys.values() for key in keys
            if _row_visible(form, key)]


def test_every_warning_mark_sits_in_one_column_whether_or_not_its_row_can_warn(qtbot):
    form = _laid_out(qtbot, ParamForm(WORKFLOW_REGISTRY["wan22_i2v"].param_definitions(),
                                      size_deriver=lambda values: (464, 912)))

    outside_the_size_margin = [key for key in _shown_keys(form)
                               if param_sections.section_title(key) != "Size"]
    lefts = {key: _left(form, form._warning_marks[key]) for key in outside_the_size_margin}

    assert {"steps", "noise_seed", "lora_strength_high", "scene_frames"} <= set(lefts)
    assert len(set(lefts.values())) == 1, lefts


def _gap_after_label(form, key):
    label = _label_beside(form, key)
    return _left(form, _field_of(form, key)) - _left(form, label) - label.width()


def test_every_field_starts_as_far_from_its_label_whether_or_not_it_can_warn(qtbot):
    form = _laid_out(qtbot, ParamForm(WORKFLOW_REGISTRY["wan22_i2v"].param_definitions(),
                                      size_deriver=lambda values: (464, 912)))

    gaps = {key: _gap_after_label(form, key) for key in _shown_keys(form)}
    assert {"steps", "noise_seed", "width", "scene_frames"} <= set(gaps)
    assert len(set(gaps.values())) == 1, gaps


def _items_wearing(dropdown, icon):
    return {dropdown.itemText(i) for i in range(dropdown.count())
            if dropdown.itemIcon(i).cacheKey() == icon.cacheKey()}


def test_the_recommended_choices_wear_a_thumbs_up_and_the_rest_a_blank_as_wide(qtbot):
    form = ParamForm(WORKFLOW_REGISTRY["sdxl_t2i"].param_definitions())
    qtbot.addWidget(form)

    form.mark_recommended({"sampler_name": ("euler_ancestral", "dpmpp_2m"), "scheduler": ()})

    samplers, spacings = form._widgets["sampler_name"], form._widgets["scheduler"]
    assert _items_wearing(samplers, icons.thumbs_up_icon()) == {"euler_ancestral", "dpmpp_2m"}
    assert len(_items_wearing(samplers, icons.unmarked_icon())) == samplers.count() - 2
    assert len(_items_wearing(spacings, icons.unmarked_icon())) == spacings.count()


def _item_tooltip(dropdown, text):
    return dropdown.itemData(dropdown.findText(text), Qt.ItemDataRole.ToolTipRole)


def test_a_recommended_choices_tooltip_opens_with_recommended(qtbot):
    form = ParamForm(WORKFLOW_REGISTRY["sdxl_t2i"].param_definitions())
    qtbot.addWidget(form)
    samplers = form._widgets["sampler_name"]

    form.mark_recommended({"sampler_name": ("euler_ancestral",), "scheduler": ()})

    assert _item_tooltip(samplers, "euler_ancestral") == shaped(
        option_help("sampler_name", "euler_ancestral"), lead="Recommended.")
    assert _item_tooltip(samplers, "heun") == option_help("sampler_name", "heun")
    form.mark_recommended({"sampler_name": (), "scheduler": ()})
    assert _item_tooltip(samplers, "euler_ancestral") == option_help(
        "sampler_name", "euler_ancestral")


class _Lends:
    def lends(self, prompt_id, kind):
        return f"{kind}/{prompt_id}.file [output]" if prompt_id.startswith(kind) else None

    def item_of(self, held):
        return held.split("/")[1].split(".")[0] if held.startswith(("image/", "video/")) else None

    def named(self, name):
        return {"AB12CD34 001": "image1"}.get(name)

    def name_of(self, held):
        return "AB12CD34 001" if "image1" in held else held

    def preview(self, held):
        return (None, None)


def _let_go(zone, prompt_id):
    mime = generation_mime(prompt_id)
    event = QDropEvent(QPointF(1, 1), Qt.DropAction.CopyAction, mime,
                       Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
    zone.dropEvent(event)


@pytest.mark.parametrize("kind", ["image", "video"])
def test_an_image_or_video_input_is_a_drop_zone_that_reads_back_what_it_holds(qtbot, kind):
    form = ParamForm([ParamDef("source", "Source", kind, "")])
    qtbot.addWidget(form)
    zone = form._widgets["source"]
    assert isinstance(zone, DropZone)
    assert form.get_values()["source"] == ""
    assert "source" not in form._browse_buttons
    assert [action.text() for action in zone.menu().actions()] == ["Paste Origenerator name",
                                                                   "Browse..."]

    form.set_values({"source": "C:/somewhere/scene one.mp4"})

    assert zone.current_id() == "C:/somewhere/scene one.mp4"
    assert form.get_values()["source"] == "C:/somewhere/scene one.mp4"


def test_a_dropped_item_lends_the_zone_the_file_the_gallery_says(qtbot):
    form = ParamForm([ParamDef("input_image", "Image", "image", ""),
                      ParamDef("video", "Video to Perform", "video", "")], items=_Lends())
    qtbot.addWidget(form)
    edits = []
    form.changed.connect(lambda: edits.append(form.get_values()))

    _let_go(form._widgets["input_image"], "image1")
    _let_go(form._widgets["video"], "image1")

    assert form.get_values()["input_image"] == "image/image1.file [output]"
    assert form.get_values()["video"] == ""
    assert edits[-1]["input_image"] == "image/image1.file [output]"
    assert form._widgets["input_image"].toolTip() == "AB12CD34 001"


def test_a_dropped_item_is_named_under_the_zones_image(qtbot):
    form = ParamForm([ParamDef("input_image", "Image", "image", "")], items=_Lends())
    qtbot.addWidget(form)

    _let_go(form._widgets["input_image"], "image1")

    assert form._widgets["input_image"]._caption.text() == "AB12CD34 001"


def test_clicking_a_held_item_leads_back_to_it(qtbot):
    form = ParamForm([ParamDef("input_image", "Image", "image", "")], items=_Lends())
    qtbot.addWidget(form)
    led_to = []
    form.item_activated.connect(led_to.append)
    zone = form._widgets["input_image"]

    form.set_values({"input_image": "C:/elsewhere/photo.png"})
    qtbot.mouseClick(zone, Qt.MouseButton.LeftButton)
    form.set_values({"input_image": "image/image1.file [output]"})
    qtbot.mouseClick(zone, Qt.MouseButton.LeftButton)

    assert led_to == ["image1"]


def test_a_lora_dropdowns_tooltip_ends_with_when_its_picked_lora_was_trained(
        qtbot, installed_models, titled_models):
    titled_models({"example_look": "Example Look 1.0"})
    for name in ("example_look", "example_style"):
        installed_models.add("loras", f"{name}.safetensors", arch="krea2", lora=True,
                             metadata={"ss_training_finished_at": "1792851468.891"})
    form = ParamForm([ParamDef("lora", "LoRA", "dropdown", NO_LORA, options=[
        NO_LORA, "example_look.safetensors", "example_style.safetensors"])], lora_keys=("lora",))
    qtbot.addWidget(form)
    dropdown = form._widgets["lora"]
    trained = f"Trained {datetime.fromtimestamp(1792851468.891).astimezone():%Y-%m-%d %H:%M}."
    assert dropdown.toolTip() == param_help("lora")

    dropdown.setCurrentIndex(dropdown.findData("example_look.safetensors"))
    assert dropdown.toolTip() == f"{param_help('lora')} {trained}"

    form.set_values({"lora": "example_style.safetensors"})
    assert dropdown.toolTip() == param_help("lora")


def _lora_form(qtbot, **options):
    form = ParamForm([ParamDef("lora", "LoRA", "dropdown", NO_LORA,
                               options=[NO_LORA, "example_look.safetensors"])], **options)
    qtbot.addWidget(form)
    return form


_FILED = {"raw_model": "Krea 2", "turbo_model": "Krea 2 Turbo", "speed_up": "Krea 2 Raw",
          "a_look": "Krea 2"}


def _offered(dropdown) -> list:
    return [dropdown.itemData(row) for row in range(dropdown.count())]


def _model_and_its_lora(qtbot, recorded_base_models, model):
    recorded_base_models(_FILED)
    form = ParamForm([
        ParamDef("unet", "Model", "dropdown", model,
                 options=["raw_model.safetensors", "turbo_model.safetensors"]),
        ParamDef("lora", "LoRA", "dropdown", "None", beside_model="unet",
                 options=["None", "speed_up.safetensors", "a_look.safetensors"]),
    ])
    qtbot.addWidget(form)
    return form


def test_a_lora_row_offers_training_only_while_the_form_is_handed_an_offer(qtbot, tmp_path, monkeypatch):
    form = _lora_form(qtbot, lora_keys=("lora",))
    controls = form._training_controls["lora"]
    assert controls.isHidden()
    opened = []
    monkeypatch.setattr(training_controls, "open_in_explorer", opened.append)
    asked = []
    form.train_requested.connect(asked.append)

    form.offer_training("lora", TrainingOffer(label="Retrain", enabled=True, tooltip="Trains it.",
                                              pictures=87, folder=tmp_path))

    assert not controls.isHidden()
    assert (controls.train.text(), controls.train.isEnabled(), controls.train.toolTip()) == (
        "Retrain", True, "Trains it.")
    assert controls.pictures.text() == "87 pictures"
    assert controls.pictures.toolTip() == str(tmp_path)
    controls.train.click()
    assert asked == ["lora"]
    controls.folder.click()
    assert opened == [tmp_path]

    form.offer_training("lora", TrainingOffer(label="Retrain", enabled=True, tooltip="Trains it.",
                                              pictures=1, folder=tmp_path), running="Training 10%")
    assert (controls.train.text(), controls.train.isEnabled()) == ("Training 10%", False)
    assert controls.pictures.text() == "1 picture"

    form.offer_training("lora", None)
    assert controls.isHidden()


def test_a_form_told_no_lora_keys_offers_no_training(qtbot):
    form = _lora_form(qtbot)

    assert form._training_controls == {}


def test_a_lora_filed_apart_from_the_picked_model_is_not_offered(
        qtbot, recorded_base_models):
    form = _model_and_its_lora(qtbot, recorded_base_models, "turbo_model.safetensors")

    assert _offered(form._widgets["lora"]) == ["None", "a_look.safetensors"]


def test_picking_another_model_offers_the_loras_made_for_it(qtbot, recorded_base_models):
    form = _model_and_its_lora(qtbot, recorded_base_models, "turbo_model.safetensors")
    unet = form._widgets["unet"]

    unet.setCurrentIndex(unet.findData("raw_model.safetensors"))

    assert _offered(form._widgets["lora"]) == [
        "None", "speed_up.safetensors", "a_look.safetensors"]


def test_a_lora_picked_beside_one_model_stays_picked_when_another_model_is(
        qtbot, recorded_base_models):
    form = _model_and_its_lora(qtbot, recorded_base_models, "raw_model.safetensors")
    form.set_values({"lora": "speed_up.safetensors"})

    form.set_values({"unet": "turbo_model.safetensors"})

    assert form.get_values()["lora"] == "speed_up.safetensors"


def test_every_krea_2_t2i_lora_row_follows_the_model_picked_beside_it(
        qtbot, installed_models, recorded_base_models):
    for model in ("raw_model", "turbo_model"):
        installed_models.add("diffusion_models", f"{model}.safetensors", arch="krea2")
    for lora in ("speed_up", "a_look"):
        installed_models.add("loras", f"{lora}.safetensors", arch="krea2", lora=True)
    recorded_base_models(_FILED)
    form = ParamForm(WORKFLOW_REGISTRY["krea2_t2i"].param_definitions())
    qtbot.addWidget(form)

    form.set_values({"unet": "turbo_model.safetensors"})

    assert [_offered(form._widgets[key]) for key in ("lora", "lora_2", "lora_3")] == [
        ["None", "a_look.safetensors"]] * 3



def _grayed(field) -> list[tuple[int, int, str]]:
    return [(span.start, span.length, span.format.foreground().color().name())
            for span in field.document().firstBlock().layout().formats()]


_READ = " ".join(["rain"] * 76)


def test_a_prompt_grays_the_words_its_reader_never_reads(qtbot):
    form = ParamForm([ParamDef("audio_prompt", "Positive Prompt", "str", "", multiline=True)])
    qtbot.addWidget(form)
    form.set_values({"audio_prompt": f"{_READ} on a tin roof"})

    form.show_readings({"audio_prompt": word_reading(76, CUT_OFF)})

    (box,) = form._widgets["audio_prompt"].boxes()
    assert _grayed(box) == [(len(_READ) + 1, len("on a tin roof"), TEXT_MUTED.name())]


def test_a_prompt_read_to_its_end_grays_nothing(qtbot):
    form = ParamForm([ParamDef("audio_prompt", "Positive Prompt", "str", "", multiline=True)])
    qtbot.addWidget(form)
    form.set_values({"audio_prompt": f"{_READ} on a tin roof"})
    form.show_readings({"audio_prompt": word_reading(76, CUT_OFF)})

    form.set_values({"audio_prompt": "rain on a tin roof"})

    (box,) = form._widgets["audio_prompt"].boxes()
    assert _grayed(box) == []

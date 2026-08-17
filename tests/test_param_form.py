import pytest

from PyQt6.QtWidgets import QApplication, QLabel, QPushButton, QWidget

from origenerator.workflows.base import ParamDef
from origenerator.workflows import WORKFLOW_REGISTRY
from origenerator.gui.stylesheet import build_stylesheet
from origenerator.gui import param_sections
from origenerator.gui.collapsible_section import CollapsibleSection
from shared_ui.check_box import CheckBox
from shared_ui.fonts import FONT_UI, SIZE_HEADING, make_font
from origenerator.gui.param_form import ParamForm


def test_field_labels_fit_the_heading_font(qtbot):
    """A long label must not have its first characters lopped off.

    The form runs at the app's heading font, and labels like "LoRA Strength
    (High)" are wider than the old fixed 120px column; right-aligned, the
    overflow used to clip the *start* of the text. The label column must size
    itself to the widest label instead.
    """
    label_text = "LoRA Strength (High)"
    form = ParamForm([
        ParamDef("lora_strength_high", label_text, "float", 1.0,
                 min_val=0.0, max_val=2.0, step=0.05),
    ])
    form.setFont(make_font(FONT_UI, SIZE_HEADING))
    qtbot.addWidget(form)
    form._sections["Model & LoRA"].set_collapsed(False)  # its section starts folded
    form.show()
    qtbot.waitExposed(form)

    label = next(w for w in form.findChildren(QLabel) if w.text() == label_text)
    assert label.width() >= label.fontMetrics().horizontalAdvance(label_text)


def test_browse_button_fits_its_caption(qtbot):
    """The Browse button must show its whole caption, not a clipped "B".

    At the heading font, with the stylesheet's horizontal padding, "Browse..."
    is wider than the old fixed 80px width. The button must size to its content
    — matching a reference button under the same font and stylesheet.
    """
    form = ParamForm([ParamDef("input_image", "Input Image", "image", "")])
    form.setStyleSheet(build_stylesheet())
    form.setFont(make_font(FONT_UI, SIZE_HEADING))
    qtbot.addWidget(form)
    form.resize(800, 200)  # a roomy panel, as the form has in the real window
    form.show()
    qtbot.waitExposed(form)

    # The width "Browse..." needs at this font + stylesheet. The sheet lives on
    # an ancestor (as it does on the real window), which Qt's sizing accounts
    # for slightly differently than a sheet set on the button itself.
    gauge = QWidget()
    gauge.setStyleSheet(build_stylesheet())
    gauge.setFont(make_font(FONT_UI, SIZE_HEADING))
    reference = QPushButton("Browse...", gauge)
    qtbot.addWidget(gauge)
    gauge.show()
    qtbot.waitExposed(gauge)

    btn = form._browse_buttons["input_image"]
    assert btn.width() >= reference.sizeHint().width()


def test_bool_param_renders_a_checkbox_and_round_trips(qtbot):
    # The enhance toggle is a "bool" ParamDef: a CheckBox field that reads and
    # writes True/False like any other value — so a stored recipe's flag comes
    # back checked/unchecked, and the emitted params carry a real bool.
    form = ParamForm([ParamDef("enhance", "Enhance", "bool", True)])
    qtbot.addWidget(form)
    assert isinstance(form._widgets["enhance"], CheckBox)
    assert form.get_values()["enhance"] is True

    changes = []
    form.changed.connect(lambda: changes.append(1))
    form.set_values({"enhance": False})
    assert form.get_values_static()["enhance"] is False
    assert changes  # unticking announced itself like any edit

    form.set_values({"enhance": True})
    assert form.get_values()["enhance"] is True


def test_seed_random_control_is_the_ticked_checkbox(qtbot):
    # The Random control must be our CheckBox, not a plain QCheckBox whose
    # native dark-style tick renders as a bare down-caret.
    form = ParamForm([ParamDef("seed", "Seed", "seed", 0)])
    qtbot.addWidget(form)
    assert isinstance(form._randomize_checks["seed"], CheckBox)


# --- copy buttons: the prompt/seed convenience the old inspect pane had ----

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
    form._widgets["positive_prompt"].setPlainText("a red fox in snow")

    form._copy_buttons["positive_prompt"].click()

    assert QApplication.clipboard().text() == "a red fox in snow"


def test_prompt_fields_are_draggable_boxes_filed_under_their_param(qtbot):
    # A prompt is the one field worth more than a few lines, so it gets the box
    # whose bottom edge drags — filed under its own key, so the height the user
    # gave Positive Prompt is the height every Positive Prompt opens at.
    from origenerator.gui.prompt_box import PromptBox

    form = ParamForm([
        ParamDef("positive_prompt", "Positive Prompt", "str", "", multiline=True),
        ParamDef("name", "Name", "str", ""),      # single-line: an ordinary field
    ])
    qtbot.addWidget(form)
    prompt = form._widgets["positive_prompt"]
    assert isinstance(prompt, PromptBox)
    assert prompt._key == "positive_prompt"
    assert not isinstance(form._widgets["name"], PromptBox)
    assert form.text_fields() == [prompt]


def test_plain_scalar_and_single_line_fields_get_no_copy_button(qtbot):
    form = ParamForm([
        ParamDef("steps", "Steps", "int", 20),
        ParamDef("cfg", "CFG", "float", 7.0),
        ParamDef("name", "Name", "str", ""),          # single-line str: retype-able
        ParamDef("input_image", "Input Image", "image", ""),
    ])
    qtbot.addWidget(form)
    assert form._copy_buttons == {}


def test_seed_keeps_its_random_checkbox_beside_the_copy_button(qtbot):
    form = ParamForm([ParamDef("seed", "Seed", "seed", 0)])
    qtbot.addWidget(form)
    assert "seed" in form._randomize_checks   # the Random control survives
    assert "seed" in form._copy_buttons        # and gains a copy button alongside


def _readonly_texts(form):
    return {lbl.text() for lbl in form.findChildren(QLabel)
            if lbl.objectName() == "readonlyParamValue"}


def test_passthrough_params_render_as_readonly_rows(qtbot):
    # A param the workflow lays out no field for (vae) shows as a read-only row in
    # the form itself — merged with the editable params, not hidden or in a
    # separate block — and still round-trips on read-back.
    form = ParamForm([ParamDef("seed", "Seed", "seed", 0)])
    qtbot.addWidget(form)
    form.set_values({"seed": 5, "vae": "sdxl.vae.safetensors"})

    assert "sdxl.vae.safetensors" in _readonly_texts(form)
    labels = {lbl.text() for lbl in form.findChildren(QLabel)}
    assert "vae" in labels  # the key labels the row
    assert form.get_values_static()["vae"] == "sdxl.vae.safetensors"


def test_readonly_rows_are_replaced_not_stacked(qtbot):
    form = ParamForm([ParamDef("seed", "Seed", "seed", 0)])
    qtbot.addWidget(form)
    form.set_values({"seed": 5, "vae": "a.safetensors"})
    form.set_values({"seed": 5, "clip": "b.safetensors"})

    values = _readonly_texts(form)
    assert "b.safetensors" in values
    assert "a.safetensors" not in values  # the prior extra row is gone, not stacked


def test_no_readonly_rows_when_every_param_has_a_field(qtbot):
    form = ParamForm([ParamDef("seed", "Seed", "seed", 0)])
    qtbot.addWidget(form)
    form.set_values({"seed": 5})
    assert _readonly_texts(form) == set()


def _field_cell_of(form, key):
    """The QHBoxLayout holding a field's input and its trailing controls.

    Fields live in per-section form layouts now, so search every ``QFormLayout``
    under the form, not one top-level one.
    """
    from PyQt6.QtWidgets import QFormLayout
    for fl in form.findChildren(QFormLayout):
        for r in range(fl.rowCount()):
            item = fl.itemAt(r, QFormLayout.ItemRole.FieldRole)
            if item is not None and item.layout() is not None:
                if item.layout().indexOf(form._widgets[key]) != -1:
                    return item.layout()
    return None


def test_seed_copy_button_sits_left_of_the_random_checkbox(qtbot):
    # The seed row reads [field] [copy] [Random ☐] — copy before the checkbox.
    form = ParamForm([ParamDef("seed", "Seed", "seed", 0)])
    qtbot.addWidget(form)
    cell = _field_cell_of(form, "seed")
    copy_i = cell.indexOf(form._copy_buttons["seed"])
    random_i = cell.indexOf(form._randomize_checks["seed"])
    assert 0 <= copy_i < random_i


def _dimension_defs():
    return [
        ParamDef("width", "Width", "int", 1280, min_val=64, max_val=4096, step=64),
        ParamDef("height", "Height", "int", 720, min_val=64, max_val=4096, step=64),
    ]


def test_swap_dimensions_button_exchanges_width_and_height(qtbot):
    form = ParamForm(_dimension_defs())
    qtbot.addWidget(form)
    assert form._swap_dimensions_btn is not None
    form._swap_dimensions_btn.click()
    vals = form.get_values()
    assert vals["width"] == 720
    assert vals["height"] == 1280


def test_no_swap_button_when_workflow_has_no_dimensions(qtbot):
    # An i2v form derives its size in-graph from the input image — no width or
    # height field, so there is nothing to swap.
    form = ParamForm([ParamDef("steps", "Steps", "int", 50, min_val=1, max_val=200)])
    qtbot.addWidget(form)
    assert form._swap_dimensions_btn is None


def test_swapping_dimensions_emits_changed(qtbot):
    # The panel refreshes its title from the form's ``changed`` signal, so a swap
    # must announce itself just as a manual edit does.
    form = ParamForm(_dimension_defs())
    qtbot.addWidget(form)
    fired = []
    form.changed.connect(lambda: fired.append(True))
    form._swap_dimensions_btn.click()
    assert fired


def test_swap_button_sits_between_the_rows_and_left_of_the_labels(qtbot):
    # The button reads as linking the pair: vertically midway between the width
    # and height rows, and in a gutter of its own to the left of the labels —
    # squeezing it into whatever space the labels left over put it on top of the
    # words. A wide label ("Positive Prompt") gives the left column real room.
    form = ParamForm([
        ParamDef("prompt", "Positive Prompt", "str", "", multiline=True),
        *_dimension_defs(),
    ])
    form.setFont(make_font(FONT_UI, SIZE_HEADING))
    qtbot.addWidget(form)
    form._sections["Dimensions"].set_collapsed(False)  # unfold so its rows lay out
    form.resize(400, 320)
    form.show()
    qtbot.waitExposed(form)

    btn = form._swap_dimensions_btn.geometry()
    width = form._widgets["width"].geometry()
    height = form._widgets["height"].geometry()

    # Halfway between the two rows, vertically.
    assert width.center().y() < btn.center().y() < height.center().y()
    # On the left — entirely clear of the input column.
    assert btn.right() <= width.left()
    # And clear of the words themselves: the labels start after its lane.
    assert btn.right() <= form._width_label.geometry().left()
    assert btn.right() <= form._height_label.geometry().left()


# --- derived dimensions: the input-image size, shown locked & unlockable ----

def _image_def():
    return ParamDef("input_image", "Input Image", "image", "")


def _sized_form(qtbot, size=(864, 480)):
    """A form for a size-deriving workflow: the deriver reports ``size`` once an
    input image is set, else None (nothing to measure yet)."""
    form = ParamForm(
        [_image_def()],
        size_deriver=lambda params: size if params.get("input_image") else None,
    )
    qtbot.addWidget(form)
    return form


def test_locked_dimensions_render_as_plain_values_not_input_boxes(qtbot):
    # Locked, each dimension shows as a plain value (a readonlyParamValue label,
    # like "batch_size 1"), not a spinbox — the stack sits on its label page.
    form = _sized_form(qtbot)
    assert "width" in form._present_keys["Dimensions"]
    assert "height" in form._present_keys["Dimensions"]
    assert form._unlock_btn is not None
    assert form._dimensions_hint is not None
    for key in ("width", "height"):
        stack = form._dim_stacks[key]
        assert stack.currentIndex() == 0                       # the value label, not the box
        assert stack.currentWidget() is form._dim_value_labels[key]
        assert form._dim_value_labels[key].objectName() == "readonlyParamValue"
    # No image yet → no size to show; the value reads as an em dash.
    assert form._dim_value_labels["width"].text() == "—"


def test_unlocking_swaps_the_plain_value_for_an_editable_box(qtbot):
    form = _sized_form(qtbot)
    form._unlock_btn.setChecked(True)
    for key in ("width", "height"):
        stack = form._dim_stacks[key]
        assert stack.currentIndex() == 1                       # now the editable spinbox
        assert stack.currentWidget() is form._widgets[key]


def test_unlock_toggle_carries_a_padlock_icon_that_flips(qtbot):
    from origenerator.gui.param_form import _LOCK_CLOSED, _LOCK_OPEN

    form = _sized_form(qtbot)
    assert form._unlock_btn.isCheckable()
    assert form._unlock_btn.text() == _LOCK_CLOSED     # locked: a closed padlock
    form._unlock_btn.setChecked(True)
    assert form._unlock_btn.text() == _LOCK_OPEN        # unlocked: an open one


def test_unlock_toggle_floats_free_and_never_shrinks_a_dimension_field(qtbot):
    # The toggle is a free child of the Dimensions content (like the swap button),
    # not stuffed into a field's cell — so neither field is smooshed to make room.
    form = _sized_form(qtbot)
    assert form._unlock_btn.parent() is form._sections["Dimensions"].content()
    assert _field_cell_of(form, "width") is None    # a plain field, no trailing cell
    assert _field_cell_of(form, "height") is None


def test_unlock_toggle_sits_between_the_rows_and_clears_the_labels(qtbot):
    # Vertically midway between the width and height rows, and entirely within the
    # reserved left gutter — so it never sits on top of the "Width"/"Height" labels.
    form = _sized_form(qtbot)
    form.setStyleSheet(build_stylesheet())
    form.setFont(make_font(FONT_UI, SIZE_HEADING))
    form._sections["Dimensions"].set_collapsed(False)
    form.resize(420, 380)
    form.show()
    qtbot.waitExposed(form)

    btn = form._unlock_btn.geometry()
    top = form._dim_stacks["width"].geometry()
    bottom = form._dim_stacks["height"].geometry()
    assert top.center().y() < btn.center().y() < bottom.center().y()

    dim_form = form._sections["Dimensions"].content_form()
    width_label = dim_form.labelForField(form._dim_stacks["width"])
    height_label = dim_form.labelForField(form._dim_stacks["height"])
    # The button is clear of both the labels and the fields — no overlap.
    assert btn.right() <= width_label.geometry().left()
    assert btn.right() <= height_label.geometry().left()
    assert btn.right() <= top.left()


def test_derived_dimensions_track_the_input_image(qtbot):
    form = _sized_form(qtbot, size=(864, 480))
    form._widgets["input_image"].setText("frame.png")
    # Both the plain locked value and the spinbox behind it follow the image.
    assert form._dim_value_labels["width"].text() == "864"
    assert form._dim_value_labels["height"].text() == "480"
    assert form._widgets["width"].value() == 864
    assert form._widgets["height"].value() == 480


def test_locked_derived_dimensions_stay_out_of_the_values(qtbot):
    # Locked, the form emits no width/height, so the payload derives the size the
    # usual way — the displayed number is informational only.
    form = _sized_form(qtbot)
    form._widgets["input_image"].setText("frame.png")
    values = form.get_values()
    assert "width" not in values and "height" not in values


def test_unlocking_lets_the_user_override_the_size(qtbot):
    form = _sized_form(qtbot)
    form._widgets["input_image"].setText("frame.png")
    fired = []
    form.changed.connect(lambda: fired.append(True))

    form._unlock_btn.setChecked(True)
    assert fired                                  # the unlock announces itself
    assert form._dim_stacks["width"].currentIndex() == 1   # editable box now showing
    form._widgets["width"].setValue(1024)
    form._widgets["height"].setValue(576)

    values = form.get_values()
    assert values["width"] == 1024 and values["height"] == 576


def test_relocking_drops_the_override_and_restores_the_derived_size(qtbot):
    form = _sized_form(qtbot, size=(864, 480))
    form._widgets["input_image"].setText("frame.png")
    form._unlock_btn.setChecked(True)
    form._widgets["width"].setValue(1024)
    form._widgets["height"].setValue(576)

    form._unlock_btn.setChecked(False)
    assert "width" not in form.get_values()       # back to deriving
    assert form._dim_stacks["width"].currentIndex() == 0   # plain value again
    assert form._dim_value_labels["width"].text() == "864"  # showing the derived size


def test_set_values_with_a_size_override_unlocks_and_shows_it(qtbot):
    # Reopening a saved override comes back unlocked with its exact size.
    form = _sized_form(qtbot)
    form.set_values({"input_image": "frame.png", "width": 720, "height": 400})
    assert form._dimensions_unlocked() is True
    assert form._widgets["width"].value() == 720
    assert form.get_values()["height"] == 400


def test_set_values_without_an_override_relocks_onto_the_derived_size(qtbot):
    form = _sized_form(qtbot, size=(864, 480))
    form.set_values({"input_image": "frame.png", "width": 720, "height": 400})
    form.set_values({"input_image": "other.png"})   # a plain config, no override
    assert form._dimensions_unlocked() is False
    assert "width" not in form.get_values()
    assert form._widgets["width"].value() == 864


def test_manual_size_workflow_has_no_unlock_control(qtbot):
    # A workflow with real width/height params fills the Dimensions section itself
    # (and gets the swap button); there's nothing to unlock.
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
        ParamDef("sampler", "Sampler", "combo", "euler", options=["euler", "dpm"]),
    ]


def test_param_form_get_values_returns_defaults(qtbot, sample_defs):
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


def test_set_values_preserves_params_without_a_field(qtbot, sample_defs):
    # A reused config carries params this form has no widget for — a workflow's
    # hidden VAE/CLIP settings. The form must echo them back unchanged (in both
    # reads) rather than dropping them, so reuse reproduces them exactly.
    form = ParamForm(sample_defs)
    qtbot.addWidget(form)
    form.set_values({"steps": 30, "vae_name": "custom.safetensors"})
    assert form.get_values()["vae_name"] == "custom.safetensors"
    assert form.get_values_static()["vae_name"] == "custom.safetensors"
    assert form.get_values()["steps"] == 30  # real fields still applied


def test_set_values_replaces_stale_passthrough(qtbot, sample_defs):
    # Reapplying a config drops hidden params the previous config carried, so an
    # earlier reuse's VAE never lingers into a later one on the same form.
    form = ParamForm(sample_defs)
    qtbot.addWidget(form)
    form.set_values({"vae_name": "first.safetensors"})
    form.set_values({"clip_name": "second.safetensors"})
    values = form.get_values()
    assert values["clip_name"] == "second.safetensors"
    assert "vae_name" not in values


def test_set_values_keeps_a_combo_value_absent_from_the_options(qtbot):
    # Reusing a past generation can carry a choice (a LoRA) whose file is no
    # longer on disk, so it isn't among the combo's scanned options. The form
    # must still show and return it rather than snapping to a default — that
    # would re-drop the very reused value it is meant to reproduce.
    form = ParamForm([ParamDef("lora", "LoRA", "combo", "a", options=["a", "b"])])
    qtbot.addWidget(form)
    form.set_values({"lora": "gone.safetensors"})
    assert form.get_values()["lora"] == "gone.safetensors"


def test_combo_default_absent_from_options_is_still_selected(qtbot):
    # A workflow's default LoRA may not be among the installed files the combo
    # lists. A fresh tab must still start on that default (and generate with it),
    # not silently snap to whatever file sorts first.
    form = ParamForm([ParamDef("lora", "LoRA", "combo", "default.safetensors",
                               options=["a.safetensors", "b.safetensors"])])
    qtbot.addWidget(form)
    assert form.get_values()["lora"] == "default.safetensors"


def test_get_values_static_does_not_randomize_seed(qtbot):
    form = ParamForm([ParamDef("seed", "Seed", "seed", 12345)])
    qtbot.addWidget(form)
    # Random box defaults to checked; the static read must ignore it.
    assert form.get_values_static()["seed"] == 12345
    assert form.get_values_static()["seed"] == 12345


def test_param_form_emits_changed_on_edit(qtbot):
    form = ParamForm([ParamDef("steps", "Steps", "int", 10, min_val=1, max_val=100)])
    qtbot.addWidget(form)
    fired = []
    form.changed.connect(lambda: fired.append(True))
    form.set_values({"steps": 42})
    assert fired


def test_seed_is_random_reflects_checkbox(qtbot):
    form = ParamForm([ParamDef("seed", "Seed", "seed", 0)])
    qtbot.addWidget(form)
    assert form.seed_is_random() is True  # Random box defaults to checked
    form.set_values({"seed": 42})
    assert form.seed_is_random() is False  # set_values unchecks it


def test_set_seed_random_re_checks_the_box(qtbot):
    form = ParamForm([ParamDef("seed", "Seed", "seed", 0)])
    qtbot.addWidget(form)
    form.set_values({"seed": 42})       # unchecks Random, pins the seed
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


def _stub_file_dialog(monkeypatch, chosen, captured=None):
    """Replace the native file dialog so Browse tests never open a window.

    Returns ``(chosen, "")`` — the ``(path, selected_filter)`` shape of
    :meth:`QFileDialog.getOpenFileName` — and, when given ``captured``, records
    the directory the dialog was asked to open in.
    """
    import origenerator.gui.param_form as pf

    def fake(parent, caption, directory, filt):
        if captured is not None:
            captured["dir"] = directory
        return chosen, ""

    monkeypatch.setattr(pf.QFileDialog, "getOpenFileName", fake)


def test_param_form_browse_button_picks_any_file(qtbot, monkeypatch):
    _stub_file_dialog(monkeypatch, "C:/Users/Example/Pictures/cat.png")

    form = ParamForm([ParamDef("input_image", "Input Image", "image", "")])
    qtbot.addWidget(form)
    form._browse_buttons["input_image"].click()

    # The full path is stored verbatim; ComfyUI's LoadImage resolves an
    # absolute path outside its input folder.
    assert form.get_values()["input_image"] == "C:/Users/Example/Pictures/cat.png"


def test_param_form_browse_cancel_keeps_existing_image(qtbot, monkeypatch):
    _stub_file_dialog(monkeypatch, "")  # an empty path is Qt's "cancelled"

    form = ParamForm([ParamDef("input_image", "Input Image", "image", "preset.png")])
    qtbot.addWidget(form)
    form._browse_buttons["input_image"].click()

    assert form.get_values()["input_image"] == "preset.png"


def test_param_form_browse_defaults_to_input_dir(qtbot, monkeypatch):
    import origenerator.gui.param_form as pf

    captured = {}
    _stub_file_dialog(monkeypatch, "", captured)

    form = ParamForm([ParamDef("input_image", "Input Image", "image", "")])
    qtbot.addWidget(form)
    form._browse_buttons["input_image"].click()

    assert captured["dir"] == str(pf.COMFYUI_INPUT_DIR)


def test_param_form_browse_opens_in_the_folder_the_param_names(qtbot, monkeypatch, tmp_path):
    # A workflow whose source images live outside ComfyUI's input folder names
    # that folder on its ParamDef, and the picker opens there instead.
    poses = tmp_path / "custom_poses"
    poses.mkdir()
    captured = {}
    _stub_file_dialog(monkeypatch, "", captured)

    form = ParamForm(
        [ParamDef("input_image", "Structure Image", "image", "", browse_dir=poses)]
    )
    qtbot.addWidget(form)
    form._browse_buttons["input_image"].click()

    assert captured["dir"] == str(poses)


def test_param_form_browse_falls_back_when_the_named_folder_is_absent(
    qtbot, monkeypatch, tmp_path
):
    # A checkout without the media library has no such folder; opening the dialog
    # on a path that isn't there drops it wherever the process happens to sit, so
    # the picker falls back to ComfyUI's input folder.
    import origenerator.gui.param_form as pf

    captured = {}
    _stub_file_dialog(monkeypatch, "", captured)

    form = ParamForm([
        ParamDef("input_image", "Structure Image", "image", "",
                 browse_dir=tmp_path / "not_installed"),
    ])
    qtbot.addWidget(form)
    form._browse_buttons["input_image"].click()

    assert captured["dir"] == str(pf.COMFYUI_INPUT_DIR)


def test_param_form_browse_starts_at_current_image_location(qtbot, monkeypatch, tmp_path):
    img = tmp_path / "cat.png"
    img.write_bytes(b"\x89PNG")
    captured = {}
    _stub_file_dialog(monkeypatch, "", captured)

    form = ParamForm([ParamDef("input_image", "Input Image", "image", str(img))])
    qtbot.addWidget(form)
    form._browse_buttons["input_image"].click()

    assert captured["dir"] == str(img)


def test_input_image_value_is_cleaned_of_invisible_wrapping_characters(qtbot):
    # The metadata panel inserts zero-width spaces into displayed paths so long
    # names wrap on screen. Pasting such a path back into the field would carry
    # those invisible characters (and any stray whitespace) into ComfyUI's
    # LoadImage, which then can't match the file. The form must return a clean
    # path so a value that looks right actually is.
    form = ParamForm([ParamDef("input_image", "Input Image", "image", "")])
    qtbot.addWidget(form)
    zwsp = chr(0x200B)  # the zero-width space _wrappable() inserts after / _ - . \
    wrapped = f"image/{zwsp}sdxl_{zwsp}t2i_{zwsp}00792_{zwsp}.{zwsp}png  "
    form.set_values({"input_image": wrapped})

    assert form.get_values()["input_image"] == "image/sdxl_t2i_00792_.png"


# --- collapsible sections: consistent grouping across workflows -------------

def _display_order(form):
    """Every field/row key in the order it renders, flattened across sections."""
    return [k for t in form._section_order for k in form._present_keys[t]]


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
    assert "steps" in form._present_keys["Sampling"]


def test_empty_sections_are_hidden(qtbot):
    form = ParamForm([ParamDef("seed", "Seed", "seed", 0)])
    qtbot.addWidget(form)
    form.show()
    qtbot.waitExposed(form)
    assert form._sections["Seed"].isHidden() is False       # has the one field
    assert form._sections["Prompts"].isHidden() is True     # no prompt → no header
    assert form._sections["Frames"].isHidden() is True


def test_prompts_and_seed_start_open_the_rest_collapsed(qtbot):
    form = ParamForm(WORKFLOW_REGISTRY["wan22_i2v"].param_definitions())
    qtbot.addWidget(form)
    assert form._sections["Prompts"].is_collapsed() is False
    assert form._sections["Seed"].is_collapsed() is False
    assert form._sections["Model & LoRA"].is_collapsed() is True
    assert form._sections["Sampling"].is_collapsed() is True
    assert form._sections["Frames"].is_collapsed() is True
    assert form._sections["Audio"].is_collapsed() is True


def test_fields_lay_out_in_canonical_order_not_param_definitions_order(qtbot):
    # Requirement: the form presents params in one fixed order regardless of the
    # order the workflow happens to declare them, so switching workflows never
    # reshuffles where a kind of setting sits.
    wf = WORKFLOW_REGISTRY["sdxl_t2i"]
    defs = wf.param_definitions()
    form = ParamForm(defs, hidden_keys=wf.enhance_keys())
    qtbot.addWidget(form)
    shown = [d.key for d in defs if d.key not in wf.enhance_keys()]
    assert _display_order(form) == sorted(shown, key=param_sections.key_rank)
    # Not vacuous: sdxl declares model-before-seed and dims-before-sampling, which
    # the canonical order reshuffles — so the two orders genuinely differ.
    assert _display_order(form) != shown


def test_shared_sections_appear_in_the_same_order_across_workflows(qtbot):
    def section_sequence(name):
        form = ParamForm(WORKFLOW_REGISTRY[name].param_definitions())
        qtbot.addWidget(form)
        return [t for t in form._section_order if form._present_keys[t]]

    sdxl = section_sequence("sdxl_t2i")
    i2v = section_sequence("wan22_i2v")
    # The sections each workflow shows are a subsequence of the one canonical
    # order — so any two workflows list their common sections identically.
    shared = [t for t in sdxl if t in i2v]
    assert [t for t in i2v if t in sdxl] == shared


def test_passthrough_row_lands_in_its_section_at_the_canonical_position(qtbot):
    # flux lays out steps and guidance but leaves cfg as a read-only passthrough;
    # cfg belongs between them in Sampling, so it must insert there, not append.
    form = ParamForm([
        ParamDef("steps", "Steps", "int", 20),
        ParamDef("guidance", "Guidance", "float", 4.5),
    ])
    qtbot.addWidget(form)
    form.set_values(
        {"steps": 20, "guidance": 4.5, "cfg": 1.0, "vae": "ae.safetensors"}
    )
    assert form._present_keys["Sampling"] == ["steps", "cfg", "guidance"]
    assert form._present_keys["Model & LoRA"] == ["vae"]


def test_hidden_params_get_no_field_and_no_read_only_row(qtbot):
    # The enhance params are off this form on purpose — everything laid out here
    # decides which gallery folder a run lands in, and an enhancement doesn't.
    # "Hidden" therefore means gone, not demoted to a read-only row.
    wf = WORKFLOW_REGISTRY["sdxl_t2i"]
    form = ParamForm(wf.param_definitions(), hidden_keys=wf.enhance_keys())
    qtbot.addWidget(form)
    shown = set(_display_order(form))
    assert shown.isdisjoint(set(wf.enhance_keys()))
    assert "enhance" not in form._widgets


def test_every_field_and_its_label_carry_the_params_help(qtbot):
    # The tooltip goes on the label as well as the input: the word is what you
    # are looking at when you wonder what a setting does.
    from origenerator.gui.param_help import param_help

    wf = WORKFLOW_REGISTRY["sdxl_t2i"]
    form = ParamForm(wf.param_definitions(), hidden_keys=wf.enhance_keys())
    qtbot.addWidget(form)
    for key, widget in form._widgets.items():
        assert widget.toolTip() == param_help(key), key
    section = form._sections["Sampling"].content_form()
    label = section.labelForField(form._widgets["steps"])
    assert label.toolTip() == param_help("steps")


def test_a_read_only_passthrough_row_is_explained_too(qtbot):
    from origenerator.gui.param_help import param_help

    form = ParamForm([ParamDef("steps", "Steps", "int", 20)])
    qtbot.addWidget(form)
    form.set_values({"steps": 20, "vae": "ae.safetensors"})
    (_title, _key, value_label) = form._readonly_rows[0]
    assert value_label.toolTip() == param_help("vae")


def test_hidden_params_stay_at_the_workflow_default_whatever_is_loaded(qtbot):
    # Loading an old enhanced run into a tab must not arm its enhancement for
    # the next Generate: enhancement is the Enhance subpanel's, applied
    # deliberately, so the form pins these at the workflow's own defaults.
    wf = WORKFLOW_REGISTRY["sdxl_t2i"]
    form = ParamForm(wf.param_definitions(), hidden_keys=wf.enhance_keys())
    qtbot.addWidget(form)
    assert form.get_values_static()["enhance"] is False

    form.set_values(dict(wf.default_params(), enhance=True, enhance_steps=44))

    values = form.get_values_static()
    assert values["enhance"] is False
    assert values["enhance_steps"] == wf.default_params()["enhance_steps"]
    # And it is still emitted, so the payload always has a value to build from.
    assert "enhance" in values


def test_clearing_passthrough_restores_the_editable_only_order(qtbot):
    form = ParamForm([
        ParamDef("steps", "Steps", "int", 20),
        ParamDef("guidance", "Guidance", "float", 4.5),
    ])
    qtbot.addWidget(form)
    form.set_values({"cfg": 1.0})
    assert form._present_keys["Sampling"] == ["steps", "cfg", "guidance"]
    form.set_values({})  # a config carrying no passthrough
    assert form._present_keys["Sampling"] == ["steps", "guidance"]


def test_a_passthrough_only_section_appears_when_a_config_supplies_it(qtbot):
    # wan22_t2i lays out no model field (the UNETs are passthrough). A fresh form
    # has no Model & LoRA section; loading a config with the UNETs reveals it.
    form = ParamForm(WORKFLOW_REGISTRY["wan22_t2i"].param_definitions())
    qtbot.addWidget(form)
    form.show()
    qtbot.waitExposed(form)
    assert form._sections["Model & LoRA"].isHidden() is True

    form.set_values({"unet_high": "hi.safetensors", "unet_low": "lo.safetensors"})
    assert form._sections["Model & LoRA"].isHidden() is False
    assert form._present_keys["Model & LoRA"] == ["unet_high", "unet_low"]


def test_the_plumbing_params_get_no_row_at_all(qtbot):
    # Removing their fields alone only demoted them to read-only rows, which is
    # still an Output section on the form. They round-trip unseen instead.
    form = ParamForm([ParamDef("steps", "Steps", "int", 20)])
    qtbot.addWidget(form)

    form.set_values({"steps": 30, "batch_size": 4, "filename_prefix": "image/x",
                     "crf": 19})

    shown = {key for _title, key, _label in form._readonly_rows}
    assert shown == set()
    assert "Output" not in form._sections
    # …and they are still handed back, so a payload built from this form works.
    values = form.get_values_static()
    assert values["batch_size"] == 4 and values["filename_prefix"] == "image/x"

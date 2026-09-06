import pytest
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication, QLabel, QPushButton, QWidget
from shared_ui.fonts import FONT_UI, SIZE_HEADING, make_font
from shared_ui.tick_control import TickControl

from origenerator.gui import param_sections
from origenerator.gui.collapsible_section import CollapsibleSection
from origenerator.gui.param_form import ParamForm
from origenerator.gui.preset_combo import PresetComboBox
from origenerator.gui.stylesheet import build_stylesheet
from origenerator.workflows import WORKFLOW_REGISTRY
from origenerator.workflows.base import ParamDef


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


def test_bool_param_renders_a_tick_control_and_round_trips(qtbot):
    # The enhance toggle is a "bool" ParamDef: a TickControl field that reads and
    # writes True/False like any other value — so a stored recipe's flag comes
    # back checked/unchecked, and the emitted params carry a real bool.
    form = ParamForm([ParamDef("enhance", "Enhance", "bool", True)])
    qtbot.addWidget(form)
    assert isinstance(form._widgets["enhance"], TickControl)
    assert form.get_values()["enhance"] is True

    changes = []
    form.changed.connect(lambda: changes.append(1))
    form.set_values({"enhance": False})
    assert form.get_values_static()["enhance"] is False
    assert changes  # unticking announced itself like any edit

    form.set_values({"enhance": True})
    assert form.get_values()["enhance"] is True


def test_seed_random_control_is_the_ticked_control(qtbot):
    # The Random control must be our TickControl, not a plain QCheckBox whose
    # native dark-style tick renders as a bare down-caret.
    form = ParamForm([ParamDef("seed", "Seed", "seed", 0)])
    qtbot.addWidget(form)
    assert isinstance(form._randomize_checks["seed"], TickControl)


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


def test_prompt_fields_are_draggable_and_filed_under_their_param(qtbot):
    # A prompt is the one field worth more than a few lines, so it gets the field
    # whose lower edge drags — filed under its own key, so the height the user
    # gave Positive Prompt is the height every Positive Prompt opens at.
    from origenerator.gui.prompt_field import PromptField

    form = ParamForm([
        ParamDef("positive_prompt", "Positive Prompt", "str", "", multiline=True),
        ParamDef("name", "Name", "str", ""),      # single-line: an ordinary field
    ])
    qtbot.addWidget(form)
    prompt = form._widgets["positive_prompt"]
    assert isinstance(prompt, PromptField)
    assert prompt._key == "positive_prompt"
    assert not isinstance(form._widgets["name"], PromptField)
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


def test_seed_keeps_its_random_tick_beside_the_copy_button(qtbot):
    form = ParamForm([ParamDef("seed", "Seed", "seed", 0)])
    qtbot.addWidget(form)
    assert "seed" in form._randomize_checks   # the Random control survives
    assert "seed" in form._copy_buttons        # and gains a copy button alongside


def test_a_written_seed_pins_itself_by_default(qtbot):
    # The still's deal: reusing a generation's settings reproduces its seed, so
    # writing one in unticks Random.
    form = ParamForm([ParamDef("seed", "Seed", "seed", 0)])
    qtbot.addWidget(form)

    form.set_values({"seed": 12345})

    assert form.seed_is_random() is False
    assert form.get_values()["seed"] == 12345


def test_a_form_that_does_not_pin_shows_a_written_seed_and_keeps_drawing(qtbot):
    # The clip's deal: the seed that made it fills the field (there to read, to
    # copy, and to lock with one click) but Random stays ticked, so the next
    # press draws a fresh one instead of re-running that clip's motion.
    form = ParamForm([ParamDef("seed", "Seed", "seed", 0)], pins_reused_seed=False)
    qtbot.addWidget(form)

    form.set_values({"seed": 12345})

    assert form._widgets["seed"].text() == "12345"
    assert form.seed_is_random() is True
    assert form.get_values_static()["seed"] == 12345   # a snapshot reads the field
    assert form.get_values()["seed"] != 12345          # a launch draws its own


def test_a_form_that_does_not_pin_still_locks_when_random_is_unticked(qtbot):
    # "Of course there will be cases when you want the seed locked" — one click.
    form = ParamForm([ParamDef("seed", "Seed", "seed", 0)], pins_reused_seed=False)
    qtbot.addWidget(form)
    form.set_values({"seed": 12345})

    form.set_seed_random(False)

    assert form.get_values()["seed"] == 12345


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


def test_seed_copy_button_sits_left_of_the_random_tick(qtbot):
    # The seed row reads [field] [copy] [Random ☐] — copy before the tick.
    form = ParamForm([ParamDef("seed", "Seed", "seed", 0)])
    qtbot.addWidget(form)
    cell = _field_cell_of(form, "seed")
    copy_i = cell.indexOf(form._copy_buttons["seed"])
    random_i = cell.indexOf(form._randomize_checks["seed"])
    assert 0 <= copy_i < random_i


def _row_label(form, key):
    """The "Width"/"Height" word beside a field, as its section's form lays it."""
    return form._sections["Dimensions"].content_form().labelForField(
        form._widgets[key])


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
    assert btn.right() <= _row_label(form, "width").geometry().left()
    assert btn.right() <= _row_label(form, "height").geometry().left()


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


def test_locked_dimensions_render_as_plain_values_not_input_fields(qtbot):
    # Locked, each dimension shows as a plain value (a readonlyParamValue label,
    # like "batch_size 1"), not a spinner — the stack sits on its label page.
    form = _sized_form(qtbot)
    assert "width" in form._present_keys["Dimensions"]
    assert "height" in form._present_keys["Dimensions"]
    assert form._unlock_btn is not None
    assert form._dimensions_hint is not None
    for key in ("width", "height"):
        stack = form._dim_stacks[key]
        assert stack.currentIndex() == 0                       # the value label, not the spinner
        assert stack.currentWidget() is form._dim_value_labels[key]
        assert form._dim_value_labels[key].objectName() == "readonlyParamValue"
    # No image yet → no size to show; the value reads as an em dash.
    assert form._dim_value_labels["width"].text() == "—"


def test_unlocking_swaps_the_plain_value_for_an_editable_field(qtbot):
    form = _sized_form(qtbot)
    form._unlock_btn.setChecked(True)
    for key in ("width", "height"):
        stack = form._dim_stacks[key]
        assert stack.currentIndex() == 1                       # now the editable spinner
        assert stack.currentWidget() is form._widgets[key]


def test_unlock_toggle_carries_a_padlock_icon_that_flips(qtbot):
    # The glyphs themselves, not the constants that set them: read back through
    # those, a toggle wearing the same padlock in both states passes.
    form = _sized_form(qtbot)
    assert form._unlock_btn.isCheckable()
    assert form._unlock_btn.text() == "🔒"     # locked: a closed padlock
    form._unlock_btn.setChecked(True)
    assert form._unlock_btn.text() == "🔓"      # unlocked: an open one


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
    lower = form._dim_stacks["height"].geometry()
    assert top.center().y() < btn.center().y() < lower.center().y()

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
    # Both the plain locked value and the spinner behind it follow the image.
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
    assert form._dim_stacks["width"].currentIndex() == 1   # editable spinner now showing
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


def test_a_float_field_keeps_the_second_decimal_place(qtbot, sample_defs):
    # A LoRA strength of 0.85 rounded to 0.8 by the field's own precision is a
    # different render, and it is what goes back into the database as the recipe.
    form = ParamForm(sample_defs)
    qtbot.addWidget(form)

    form.set_values({"cfg": 0.85})

    assert form.get_values()["cfg"] == 0.85


def test_a_number_field_with_no_stated_ceiling_takes_a_large_value(qtbot):
    # A param that names no maximum is bounded only by the form's fallback, so
    # that fallback is what "unbounded" means here — set low, the field silently
    # rewrites what the user typed.
    form = ParamForm([ParamDef("steps", "Steps", "int", 20)])
    qtbot.addWidget(form)

    form.set_values({"steps": 5000})

    assert form.get_values()["steps"] == 5000


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
    # Random tick defaults to checked; the static read must ignore it.
    assert form.get_values_static()["seed"] == 12345


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
    assert form.seed_is_random() is True  # Random tick defaults to checked
    form.set_values({"seed": 42})
    assert form.seed_is_random() is False  # set_values unchecks it


def test_set_seed_random_re_ticks_it(qtbot):
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
    assert form._sections["Video"].isHidden() is True


def test_prompts_and_seed_start_open_the_rest_collapsed(qtbot):
    form = ParamForm(WORKFLOW_REGISTRY["wan22_i2v"].param_definitions())
    qtbot.addWidget(form)
    assert form._sections["Prompts"].is_collapsed() is False
    assert form._sections["Seed"].is_collapsed() is False
    assert form._sections["Model & LoRA"].is_collapsed() is True
    assert form._sections["Sampling"].is_collapsed() is True
    assert form._sections["Video"].is_collapsed() is True
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


def _rate_def(default=24.0):
    return ParamDef("frame_rate", "Frame Rate", "float", default,
                    min_val=1.0, max_val=120.0, step=1.0,
                    options=[16, 24, 60], unit="fps")


def test_a_numeric_param_with_presets_is_an_editable_dropdown_that_emits_the_number(qtbot):
    form = ParamForm([_rate_def()])
    qtbot.addWidget(form)
    combo = form._widgets["frame_rate"]
    assert isinstance(combo, PresetComboBox)
    assert combo.currentText() == "24 fps"
    assert form.get_values()["frame_rate"] == 24.0

    changes = []
    form.changed.connect(lambda: changes.append(1))
    combo.setCurrentText("30")
    assert form.get_values()["frame_rate"] == 30.0
    assert changes

    form.set_values({"frame_rate": 60})
    assert combo.currentText() == "60 fps"
    assert form.get_values_static()["frame_rate"] == 60.0


def test_a_typed_number_past_the_range_is_clamped_and_shown_clamped_once_the_edit_ends(qtbot):
    form = ParamForm([_rate_def()])
    qtbot.addWidget(form)
    form.show()
    qtbot.waitExposed(form)
    combo = form._widgets["frame_rate"]
    combo.lineEdit().setFocus()
    combo.setCurrentText("500")
    assert form.get_values()["frame_rate"] == 120.0
    qtbot.keyClick(combo.lineEdit(), Qt.Key.Key_Return)
    assert combo.currentText() == "120 fps"


def _video_defs(max_frames=161):
    return [
        # Seconds are counted at the rate the model paces motion at (16 fps),
        # which is a fact about the model, not about the field beside it.
        ParamDef("frame_count", "Duration", "int", 81, min_val=5, max_val=max_frames,
                 step=4, options=[1, 5, 10], unit="s", rate=16.0),
        ParamDef("frame_rate", "Frame Rate", "float", 16.0, min_val=16.0, max_val=112.0,
                 step=16.0, options=[16, 32, 48], unit="fps"),
    ]


def _preset_states(combo) -> dict:
    model = combo.model()
    return {combo.itemText(i): model.item(i).isEnabled() for i in range(combo.count())}


def test_a_duration_this_model_cannot_render_is_offered_greyed_out(qtbot):
    # The same lengths are offered on every video form, and the models stop at
    # different places. Picking one past the end doesn't fail, it quietly
    # becomes the longest clip the model does render — so the list says which
    # ones those are, and how far this one actually goes.
    form = ParamForm(_video_defs(max_frames=81))
    qtbot.addWidget(form)
    duration = form._widgets["frame_count"]

    assert _preset_states(duration) == {"1 s": True, "5 s": True, "10 s": False}
    assert "5 s" in duration.model().item(2).toolTip()


def test_the_presets_a_model_can_reach_are_all_left_alone(qtbot):
    # 161 frames is 10.06 s, so every offered length is real here — and every
    # frame rate is, since none is past what the video writer accepts.
    form = ParamForm(_video_defs())
    qtbot.addWidget(form)

    assert all(_preset_states(form._widgets["frame_count"]).values())
    assert all(_preset_states(form._widgets["frame_rate"]).values())


def test_a_frame_count_is_shown_and_edited_as_seconds_at_the_models_own_rate(qtbot):
    form = ParamForm(_video_defs())
    qtbot.addWidget(form)
    duration = form._widgets["frame_count"]
    assert [duration.itemText(i) for i in range(duration.count())] == ["1 s", "5 s", "10 s"]
    assert duration.currentText() == "5 s"                 # 81 frames at 16 fps
    assert form.get_values()["frame_count"] == 81

    duration.setCurrentText("10")
    assert form.get_values()["frame_count"] == 161

    form.set_values({"frame_count": 21})
    assert duration.currentText() == "1.3 s"
    assert form.get_values_static()["frame_count"] == 21


def test_the_frames_a_duration_asks_for_dont_move_when_the_frame_rate_does(qtbot):
    # The rate decides how smooth the clip looks, not how much of it there is:
    # the extra frames are filled in afterwards, so five seconds is 81 frames of
    # sampling whether it is played at 16 fps or 48.
    form = ParamForm(_video_defs())
    qtbot.addWidget(form)
    assert form.get_values()["frame_count"] == 81
    form._widgets["frame_rate"].setCurrentText("48")
    assert form._widgets["frame_count"].currentText() == "5 s"
    assert form.get_values() == {"frame_count": 81, "frame_rate": 48.0}


def test_a_loaded_frame_count_is_shown_as_the_seconds_it_really_runs(qtbot):
    # A recipe saved before the rates were multiples carries 24 fps; it loads as
    # the reachable rate beside it, and its frames still read as their own
    # seconds rather than being restated at whatever rate came with them.
    form = ParamForm(_video_defs())
    qtbot.addWidget(form)
    form.set_values({"frame_count": 121, "frame_rate": 24.0})
    assert form._widgets["frame_count"].currentText() == "7.6 s"
    assert form._widgets["frame_rate"].currentText() == "32 fps"
    assert form.get_values_static()["frame_count"] == 121


def test_a_duration_the_model_cannot_render_settles_to_what_it_can_once_the_edit_ends(qtbot):
    form = ParamForm(_video_defs())
    qtbot.addWidget(form)
    form.show()
    qtbot.waitExposed(form)
    duration = form._widgets["frame_count"]

    duration.lineEdit().setFocus()
    duration.setCurrentText("30")
    assert form.get_values()["frame_count"] == 161
    qtbot.keyClick(duration.lineEdit(), Qt.Key.Key_Return)
    assert duration.currentText() == "10 s"     # the 161 frames it settles on


def test_a_frame_rate_the_interpolator_cannot_reach_settles_onto_one_it_can(qtbot):
    # Between two multiples there are no frames to show, and writing the file at
    # the rate asked for anyway would skew its speed. The field says so by
    # landing on the rate the clip will really be written at.
    form = ParamForm(_video_defs())
    qtbot.addWidget(form)
    form.show()
    qtbot.waitExposed(form)
    rate = form._widgets["frame_rate"]

    rate.lineEdit().setFocus()
    rate.setCurrentText("60")
    assert form.get_values()["frame_rate"] == 64.0
    qtbot.keyClick(rate.lineEdit(), Qt.Key.Key_Return)
    assert rate.currentText() == "64 fps"


# --- a story: a card per scene, its prompts and its length -----------------------

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


def test_a_story_starts_as_one_scene_whose_length_is_the_clips(qtbot):
    form = ParamForm(_scene_defs())
    qtbot.addWidget(form)
    editor = form._widgets["scene_frames"]
    assert (form._widgets["positive_prompt"] is editor is form._widgets["negative_prompt"]
            is form._widgets["scene_lines"])
    assert len(editor.fields("positive_prompt")) == 1
    assert form.get_values() == {"positive_prompt": "", "negative_prompt": "",
                                 "scene_frames": [81], "scene_lines": [""], "frame_count": 81}
    # One row stands for the four, labeled as the scenes: a prompt row of the
    # form's own beside the cards would read as the clip's where the cards' are
    # the scenes'.
    assert form._present_keys["Prompts"] == ["scene_frames"]


def test_adding_a_scene_gives_it_its_own_prompt_and_length_and_the_clip_adds_up(qtbot):
    # Every scene after the first starts on the frame before it, so 5 s and
    # 10 s of scenes make 81 + 160 frames of clip, and the story is stored as
    # one prompt with a scene break between the two texts.
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
    # A negative mostly holds across a story, so a new scene starts with the one
    # before it rather than blank; edited apart, each is stored as its own text,
    # a scene break between them like the prompts.
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
    assert [combo.currentText() for combo in [scene.length for scene in editor._scenes]] == ["10 s", "5 s", "10 s"]
    assert [field.toPlainText() for field in editor.fields("scene_lines")] == ["hi", "", "bye"]
    assert form.get_values_static() == stored


def test_a_recipe_from_before_scenes_loads_as_one_scene_of_the_clips_length(qtbot):
    form = ParamForm(_scene_defs())
    qtbot.addWidget(form)
    form.set_values({"positive_prompt": "one shot", "negative_prompt": "blurry", "frame_count": 121})
    editor = form._widgets["scene_frames"]
    assert [field.toPlainText() for field in editor.fields("positive_prompt")] == ["one shot"]
    assert [field.toPlainText() for field in editor.fields("negative_prompt")] == ["blurry"]
    assert [combo.currentText() for combo in [scene.length for scene in editor._scenes]] == ["7.6 s"]
    values = form.get_values_static()
    assert (values["scene_frames"], values["frame_count"]) == ([121], 121)
    assert values["negative_prompt"] == "blurry"


def test_a_whole_clip_negative_carries_on_into_every_scene_of_a_story(qtbot):
    # A story made when the negative was the clip's has one text for three
    # scenes; the graph keeps it out of every scene, and so the cards show it
    # on every scene -- what is seen is what renders.
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


def test_the_clip_length_reads_as_the_scenes_total_and_takes_no_typing(qtbot):
    form = ParamForm(_scene_defs())
    qtbot.addWidget(form)
    editor = form._widgets["scene_frames"]
    duration = form._widgets["frame_count"]
    assert isinstance(duration, QLabel)
    editor.add_scene()
    [scene.length for scene in editor._scenes][0].setCurrentText("10")
    assert duration.text() == "15 s"          # 161 + 80 frames, at 16 fps
    assert form.get_values()["frame_count"] == 241


def test_scene_prompts_are_text_fields_for_find_and_copy(qtbot):
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
    assert form._field_text("positive_prompt") == "a\n---\nb"
    assert form._field_text("negative_prompt") == "\n---\nn"


def test_each_box_on_a_card_says_what_it_is(qtbot):
    # Three fields to a card, so each is captioned and carries its param's help;
    # the lines field says as well that what goes in it is spoken.
    from origenerator.gui.eliding import ElidingLabel
    from origenerator.gui.param_help import param_help

    form = ParamForm(_scene_defs())
    qtbot.addWidget(form)
    scene = form._widgets["scene_frames"]._scenes[0]
    captions = {label.text() for label in scene.findChildren(ElidingLabel)}
    assert {"Positive Prompt", "Negative Prompt", "Her Lines"} <= captions
    assert scene.fields["negative_prompt"].toolTip() == param_help("negative_prompt")
    assert "spoken" in scene.fields["scene_lines"].placeholderText().lower()


def test_a_workflow_that_cannot_speak_shows_no_lines_box(qtbot):
    # The loop has no lines param, so its cards carry no field for one: a field
    # that nothing reads would be an invitation to type into the void.
    from origenerator.gui.eliding import ElidingLabel

    form = ParamForm([pd for pd in _scene_defs() if pd.key != "scene_lines"])
    qtbot.addWidget(form)
    editor = form._widgets["scene_frames"]
    editor.add_scene()
    for scene in editor._scenes:
        assert "scene_lines" not in scene.fields
        assert "Her Lines" not in {label.text() for label in scene.findChildren(ElidingLabel)}
    assert editor.lines() == []
    assert "scene_lines" not in form.get_values()


def test_a_recipe_whose_lone_scene_disagrees_with_the_clip_follows_the_clip(qtbot):
    # A recipe from the overlay carries the clip length over the workflow's
    # default scene list; the clip length is what the graph runs a lone scene
    # for, so it is what the form shows and emits.
    form = ParamForm(_scene_defs())
    qtbot.addWidget(form)
    form.set_values({"positive_prompt": "x", "frame_count": 121, "scene_frames": [81]})
    editor = form._widgets["scene_frames"]
    assert [combo.currentText() for combo in [scene.length for scene in editor._scenes]] == ["7.6 s"]
    assert form.get_values_static()["frame_count"] == 121


# --- the voice her lines are spoken in -----------------------------------------


def _voice_defs():
    from origenerator.speech import VOICE_OPTIONS

    return [
        ParamDef("voice", "Voice", "combo", "Vivian", options=list(VOICE_OPTIONS)),
        ParamDef("voice_sample", "Voice Sample", "audio", ""),
        ParamDef("voice_sample_text", "Voice Sample Says", "str", "", multiline=True),
    ]


def _row_visible(form, key):
    title = param_sections.section_title(key)
    return form._sections[title].content_form().isRowVisible(form._present_keys[title].index(key))


def test_the_voice_sample_rows_show_only_for_the_custom_voice(qtbot):
    # A preset needs no recording, and two fields under it read as a second
    # thing to fill in; they appear when the Voice is the custom one, and go
    # with a recipe that stored it.
    from origenerator.speech import CUSTOM_VOICE

    form = ParamForm(_voice_defs())
    qtbot.addWidget(form)
    assert not _row_visible(form, "voice_sample") and not _row_visible(form, "voice_sample_text")
    form._widgets["voice"].setCurrentText(CUSTOM_VOICE)
    assert _row_visible(form, "voice_sample") and _row_visible(form, "voice_sample_text")
    form.set_values({"voice": "Serena"})
    assert not _row_visible(form, "voice_sample")
    form.set_values({"voice": CUSTOM_VOICE, "voice_sample": "C:/v/her.wav", "voice_sample_text": "Hi."})
    assert _row_visible(form, "voice_sample")
    assert form.get_values()["voice_sample"] == "C:/v/her.wav"


def test_a_voice_sample_is_picked_with_a_browse_button(qtbot, monkeypatch):
    import origenerator.gui.param_form as pf

    asked = {}

    def fake(parent, caption, directory, kinds):
        asked.update(caption=caption, kinds=kinds)
        return "C:/v/her.wav", ""

    monkeypatch.setattr(pf.QFileDialog, "getOpenFileName", fake)
    form = ParamForm(_voice_defs())
    qtbot.addWidget(form)
    form._browse_buttons["voice_sample"].click()
    assert form._widgets["voice_sample"].text() == "C:/v/her.wav"
    assert "Voice Sample" in asked["caption"] and "*.wav" in asked["kinds"]
    assert form.get_values()["voice_sample"] == "C:/v/her.wav"

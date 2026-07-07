import pytest

from PyQt6.QtWidgets import QApplication, QLabel, QPushButton, QWidget

from origenerator.workflows.base import ParamDef
from origenerator.gui.stylesheet import build_stylesheet
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


def test_swap_button_sits_between_the_rows_and_left_of_the_fields(qtbot):
    # The button reads as linking the pair: vertically midway between the width
    # and height rows, and off to the left of the labels rather than trailing a
    # field. A wide label ("Positive Prompt") gives the left column real room.
    form = ParamForm([
        ParamDef("prompt", "Positive Prompt", "str", "", multiline=True),
        *_dimension_defs(),
    ])
    form.setFont(make_font(FONT_UI, SIZE_HEADING))
    qtbot.addWidget(form)
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

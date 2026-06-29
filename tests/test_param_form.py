import pytest

from origenerator.workflows.base import ParamDef
from origenerator.gui.check_box import CheckBox
from origenerator.gui.param_form import ParamForm


def test_seed_random_control_is_the_ticked_checkbox(qtbot):
    # The Random control must be our CheckBox, not a plain QCheckBox whose
    # native dark-style tick renders as a bare down-caret.
    form = ParamForm([ParamDef("seed", "Seed", "seed", 0)])
    qtbot.addWidget(form)
    assert isinstance(form._randomize_checks["seed"], CheckBox)


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


def test_param_form_browse_button_picks_image(qtbot, monkeypatch):
    import origenerator.gui.param_form as pf

    class _FakePicker:
        def __init__(self, parent=None):
            pass

        def exec(self):
            return 1  # QDialog.Accepted

        def selected_image(self):
            return "cat.png"

    monkeypatch.setattr(pf, "ImagePickerDialog", _FakePicker)

    form = ParamForm([ParamDef("input_image", "Input Image", "image", "")])
    qtbot.addWidget(form)
    form._browse_buttons["input_image"].click()

    assert form.get_values()["input_image"] == "cat.png"


def test_param_form_browse_cancel_keeps_existing_image(qtbot, monkeypatch):
    import origenerator.gui.param_form as pf

    class _CancelPicker:
        def __init__(self, parent=None):
            pass

        def exec(self):
            return 0  # QDialog.Rejected

        def selected_image(self):
            return None

    monkeypatch.setattr(pf, "ImagePickerDialog", _CancelPicker)

    form = ParamForm([ParamDef("input_image", "Input Image", "image", "preset.png")])
    qtbot.addWidget(form)
    form._browse_buttons["input_image"].click()

    assert form.get_values()["input_image"] == "preset.png"

from __future__ import annotations

import pytest

from origenerator import request_settings
from origenerator.workflows.base import ParamDef, ParamType

DEFS = [
    ParamDef("positive_prompt", "Positive Prompt", ParamType.STR, "", multiline=True),
    ParamDef("seed", "Seed", ParamType.SEED, 1),
    ParamDef("width", "Width", ParamType.INT, 1024, min_val=512, max_val=2048, step=64),
    ParamDef("lora_strength", "LoRA Strength", ParamType.FLOAT, 0.8, min_val=0.0, max_val=2.0),
    ParamDef("sampler_name", "Sampler", ParamType.DROPDOWN, "euler", options=["euler", "dpmpp_2m"]),
    ParamDef("human", "Human inspired", ParamType.BOOL, False),
    ParamDef("input_image", "Image", ParamType.IMAGE, ""),
]
PARAMS = {"positive_prompt": "a cat", "seed": 7, "width": 1024, "lora_strength": 0.8,
          "sampler_name": "euler", "human": False, "input_image": "x.png"}


def _told():
    return request_settings.settings_to_tell(DEFS, PARAMS)


def test_the_model_is_told_the_numbers_choices_and_switches_never_prompts_seeds_or_files():
    assert [setting.key for setting in _told()] == [
        "width", "lora_strength", "sampler_name", "human"]
    assert [setting.value for setting in _told()] == [1024, 0.8, "euler", False]


def test_each_setting_is_told_with_its_label_range_or_choices():
    text = request_settings.as_told(_told())

    assert "Width [width]: 1024, a whole number from 512 to 2048" in text
    assert "LoRA Strength [lora_strength]: 0.8, a number from 0.0 to 2.0" in text
    assert "Sampler [sampler_name]: euler, one of euler, dpmpp_2m" in text
    assert "Human inspired [human]: off, on or off" in text


def test_the_answers_changes_are_taken_in_each_settings_own_kind():
    changes = request_settings.changes_asked(
        {"width": "1216", "lora_strength": "1.3", "sampler_name": "DPMPP_2M", "human": "on"},
        _told())

    assert changes == {"width": 1216, "lora_strength": 1.3, "sampler_name": "dpmpp_2m",
                       "human": True}


def test_a_number_past_its_range_stops_at_the_edge_and_a_setting_may_be_named_by_its_label():
    changes = request_settings.changes_asked({"Width": 9000, "LoRA Strength": -1}, _told())

    assert changes == {"width": 2048, "lora_strength": 0.0}


def test_unknown_settings_unchanged_values_and_choices_off_the_list_are_dropped():
    changes = request_settings.changes_asked(
        {"steps": 30, "width": 1024, "sampler_name": "fancy", "human": "maybe"}, _told())

    assert changes == {}


def test_nothing_answered_changes_nothing():
    assert request_settings.changes_asked(None, _told()) == {}
    assert request_settings.changes_asked("not a table", _told()) == {}


def test_changes_are_described_by_label_before_and_after():
    assert request_settings.described({"width": 1216, "human": True}, _told()) == [
        ("Width", "1024", "1216"), ("Human inspired", "off", "on")]


def test_a_number_the_model_answered_in_words_is_dropped():
    assert request_settings.changes_asked({"width": "wider"}, _told()) == {}


_LORA_ROW = ParamDef("lora", "LoRA 1", ParamType.DROPDOWN, "None",
                     options=["None", "example_style.safetensors", "example_style_11.safetensors"],
                     folder="loras")


def test_a_model_file_is_told_and_taken_by_its_title(titled_models, worded_loras):
    titled_models({"example_style": "Example Style 1.0", "example_style_11": "Other Look 2.0"})
    worded_loras({})
    (lora,) = request_settings.settings_to_tell([_LORA_ROW], {"lora": "example_style.safetensors"})

    assert lora.told() == ("- LoRA 1 [lora]: Example Style 1.0, one of None, Example Style 1.0, "
                           "Other Look 2.0")
    assert lora.shown() == "Example Style 1.0"
    assert request_settings.changes_asked({"lora": "other look 2.0"}, [lora]) == {
        "lora": "example_style_11.safetensors"}


def test_a_lora_is_told_with_its_trigger_words_and_the_newest_version_of_each_is_named(
        titled_models, worded_loras):
    titled_models({"example_style": "Example Style 1.0", "example_style_11": "Example Style 1.1"})
    worded_loras({"example_style": ["exmplstyle"], "example_style_11": ["exmplnew", "newer"]})
    (lora,) = request_settings.settings_to_tell([_LORA_ROW], {"lora": "example_style.safetensors"})

    assert lora.told() == (
        "- LoRA 1 [lora]: Example Style 1.0 (trigger word exmplstyle), one of None, "
        "Example Style 1.0 (trigger word exmplstyle), "
        "Example Style 1.1 (trigger words exmplnew and newer; the newest Example Style)")
    assert lora.shown() == "Example Style 1.0"
    assert request_settings.changes_asked({"lora": "Example Style 1.1"}, [lora]) == {
        "lora": "example_style_11.safetensors"}


def test_a_lora_row_beside_a_model_offers_only_the_loras_made_for_that_model(
        titled_models, worded_loras, recorded_base_models):
    titled_models({"example_style": "Example Style 1.0", "example_style_11": "Other Look 2.0"})
    worded_loras({})
    recorded_base_models({"krea": "Krea 2", "example_style": "Krea 2", "example_style_11": "SDXL 1.0"})
    row = ParamDef("lora", "LoRA 1", ParamType.DROPDOWN, "None", options=_LORA_ROW.options,
                   folder="loras", beside_model="unet")

    (lora,) = request_settings.settings_to_tell([row], {"lora": "None", "unet": "krea.safetensors"})

    assert lora.told() == "- LoRA 1 [lora]: None, one of None, Example Style 1.0"
    assert request_settings.changes_asked({"lora": "Other Look 2.0"}, [lora]) == {}


_SIZE = [ParamDef("width", "Width", ParamType.INT, 1024, min_val=512, max_val=2048, step=16),
         ParamDef("height", "Height", ParamType.INT, 1024, min_val=512, max_val=2048, step=16)]


@pytest.mark.parametrize(("width", "height", "shape"), [
    (720, 1280, "portrait (taller than wide)"),
    (1280, 720, "landscape (wider than tall)"),
    (1024, 1024, "square"),
])
def test_width_and_height_are_told_together_as_the_shape_they_make(width, height, shape):
    text = request_settings.as_told(
        request_settings.settings_to_tell(_SIZE, {"width": width, "height": height}))

    assert text.endswith(
        f"Width {width} and Height {height} together make the image {shape}. Portrait, "
        "landscape and square are a matter of Width and Height and never of the prompts: portrait "
        "means Height greater than Width, landscape means Width greater than Height, square means "
        "the two equal, so to make a landscape image portrait or the reverse, swap the two numbers.")


def test_without_both_width_and_height_no_shape_is_told():
    text = request_settings.as_told(request_settings.settings_to_tell(_SIZE[:1], {"width": 720}))

    assert "portrait" not in text

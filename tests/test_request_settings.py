"""The settings a Request may change besides the prompts: which ones the model
is told about, how, and what of its answer the form takes."""
from __future__ import annotations

from origenerator import request_settings
from origenerator.workflows.base import ParamDef, ParamType

DEFS = [
    ParamDef("positive_prompt", "Positive Prompt", ParamType.STR, "", multiline=True),
    ParamDef("seed", "Seed", ParamType.SEED, 1),
    ParamDef("width", "Width", ParamType.INT, 1024, min_val=512, max_val=2048, step=64),
    ParamDef("lora_strength", "LoRA Strength", ParamType.FLOAT, 0.8, min_val=0.0, max_val=2.0),
    ParamDef("sampler_name", "Sampler", ParamType.COMBO, "euler", options=["euler", "dpmpp_2m"]),
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
